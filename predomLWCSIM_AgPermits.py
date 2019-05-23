"""
..module:: predomLWCSIM_AgPermits.py
  :
  :	      To be ran from PythonWin on Citrix or desktop with ArcGIS installed.
  :
  :synopsis:    perform ArcGIS geospatial processing steps in a script
  ::created:    22-May-2019
  ::Author:     Kevin A. Rodberg
  ::E-mail:     krodberg@sfwmd.gov

..Program Description::
    Read csv file identifing Permit/Application Annual Allocations and mgd
    Intersects model mesh and WU primary applications layer for selected APP_NOs from above

    Predominant (top 3) spatial area of a permit/model cell is calculated
    showing a ratio however it is only calculated as a total percentage of the GIS area
    which is served the allocation.
    
    This doesn't show the ratio of the area within the model cell which should be
    multiplied by the allocation.
    
    Another calculation is needed first.

    use AGWU_SQFT/(GIS_AREA*43570)*RATIO# so you can
    multiply by allocation and get a figure showing how much water is available to be
    applied to the model cell.
"""
import arcpy
import sys
import numpy as np
import pandas as pd
import os

arcpy.CheckOutExtension("Spatial")
arcpy.env.overwriteOutput = True
SR = arcpy.SpatialReference(2881)

workdir = r"//ad.sfwmd.gov/dfsroot/data/wsd/GIS/GISP_2012/WorkingDirectory/KAR/ModflowProcessing/PythonTools/LWCSIM"
myGDB = "PredomLWCSIM_AgPermits.gdb"

#----------------------------------------------------------------------------------------------------------
#   Create myGDB if it doesn't already exist
#----------------------------------------------------------------------------------------------------------
Myworkspace=os.path.join(workdir,myGDB)
if not arcpy.Exists(Myworkspace):
    mygdb= arcpy.CreateFileGDB_management(workdir, myGDB)

ModelMesh = '//ad.sfwmd.gov/dfsroot/data/wsd/GIS/GISP_2012/DataLib/ModelData/LWCSIM/LWCSIM_mesh.shp'

AgWUModelMesh = Myworkspace + "/AgWUModelMesh"
maxAreaAgWUMesh = Myworkspace + "/maxAreaAgWUMesh"

#----------------------------------------------------------------------------------------------------------
#   Read list of permits from csv file to filter the ArcGIS primary water use applications by permit_no
#----------------------------------------------------------------------------------------------------------
ExcelFile = 'LWC_Allocations_052219v2.csv'
AgPermitsData = os.path.join(workdir,ExcelFile)

AgPermits = pd.read_csv(AgPermitsData, delimiter=',')
permitList=list(AgPermits['PERMIT_NO'])
appList=list(AgPermits['Application'])

AgGIS = 'AgPermits.gdb'
WU_fc='WaterUsePrimary'
GISpermits = os.path.join(workdir,AgGIS)
WU_Primary = os.path.join(GISpermits,WU_fc)

WU_lyr = arcpy.MakeFeatureLayer_management(WU_Primary, "WU_Primary_lyr")
print('Before def query:',arcpy.GetCount_management(WU_lyr))

#----------------------------------------------------------------------------------------------------------
#   Create comma separated list of quoated permits for definition query
#----------------------------------------------------------------------------------------------------------
valuesWithApostrophes = [ "'{0}'".format(value) for value in appList]
commaList = ", ".join(valuesWithApostrophes)
##definitionQuery = '"ACTIVE_MOD"={1} AND "PERMIT_NO" IN ({0})'.format(commaList,"'Y'")
definitionQuery = '"APP_NO" IN ({0})'.format(commaList)

print ('Definition query defined:', definitionQuery)
arcpy.SelectLayerByAttribute_management (WU_lyr, "NEW_SELECTION", definitionQuery)

arcpy.CopyFeatures_management(WU_lyr, GISpermits+'/selectedAgPermits')
selectedAg = GISpermits+'/selectedAgPermits'

#----------------------------------------------------------------------------------------------------------
#   Create field to maintain permit/application area
#----------------------------------------------------------------------------------------------------------
arcpy.AddField_management(selectedAg, "GIS_AREA", "LONG", 9,
                          field_alias="GIS_AREA", field_is_nullable="NULLABLE")

expression = "!Shape_Area! / 43560. "
arcpy.CalculateField_management(selectedAg,"GIS_AREA",expression, "PYTHON")

#----------------------------------------------------------------------------------------------------------
#			Instersect LWCSIM Model Mesh with Selected WU primary permits
#----------------------------------------------------------------------------------------------------------
InterceptFeatures = ModelMesh + " #;" + selectedAg + " #"

print ('Beginning intersection of model mesh and selected permits')
arcpy.Intersect_analysis(in_features=InterceptFeatures,out_feature_class=AgWUModelMesh,
                         join_attributes="ALL",cluster_tolerance="#",output_type="INPUT")

print ('Calculating geometry')
arcpy.AddGeometryAttributes_management(Input_Features=AgWUModelMesh,Geometry_Properties="AREA",
                                       Length_Unit="FEET_US",Area_Unit="SQUARE_FEET_US",Coordinate_System=SR)

print ('Dissolving AgWUModelMesh')
arcpy.Dissolve_management(in_features=AgWUModelMesh,out_feature_class=maxAreaAgWUMesh,
                          dissolve_field="SEQNUM;PERMIT_NO;APP_NO;ACRES_SERVED;GIS_AREA",
                          statistics_fields="Shape_Area SUM",multi_part="MULTI_PART",
                          unsplit_lines="DISSOLVE_LINES")

print('Creating dataframes')
#----------------------------------------------------------------------------------------------------------
#   Create pandas dataframe from model mesh shapefile
#----------------------------------------------------------------------------------------------------------
arcpy.MakeFeatureLayer_management(ModelMesh, "MM_layer")
MM_nparr = arcpy.da.FeatureClassToNumPyArray('MM_layer', ['SEQNUM','ROW','COL'])
MM_df = pd.DataFrame(MM_nparr, columns=['SEQNUM','ROW','COL'])

#----------------------------------------------------------------------------------------------------------
#   Create pandas dataframe from output feature class from the intersection
#   of the Water Use Applications and the Model Mesh
#----------------------------------------------------------------------------------------------------------
arcpy.MakeFeatureLayer_management(maxAreaAgWUMesh, "AG_Mesh_lyr")
attributeList = [u'SEQNUM',u'PERMIT_NO','APP_NO',u'ACRES_SERVED','GIS_AREA',u'SUM_Shape_Area']
Ag_Mesh_nparr = arcpy.da.FeatureClassToNumPyArray('Ag_Mesh_lyr', attributeList)
Ag_Mesh_df = pd.DataFrame(Ag_Mesh_nparr, columns=attributeList)
attributeList = ['SEQNUM','PERMIT_NO','APP_NO','ACRES_SERVED','GIS_AREA','AGWU_SQFT']
Ag_Mesh_df.columns=attributeList

#----------------------------------------------------------------------------------------------------------
#   Calculate the Ratio of Permitted Acres Served vs the GIS area of the application boundary
#----------------------------------------------------------------------------------------------------------
Ag_Mesh_df['RATIO'] = Ag_Mesh_df['ACRES_SERVED']/(Ag_Mesh_df['GIS_AREA'])

print('Summarizing data')
#----------------------------------------------------------------------------------------------------------
#   Create dataframe from just intersected model mesh cells with the largest area .nth(0),
#       second largest area .nth(1) and third largest are .nth(2)
#----------------------------------------------------------------------------------------------------------
print ('First Level')
maxAreabySeq = Ag_Mesh_df.sort(['AGWU_SQFT'],ascending=False).groupby(['SEQNUM'], as_index=False).nth(0)
maxAreabySeq.columns=['SEQNUM','PERMIT_NO_1','APP_NO_1','ACRES_SERVED_1','GIS_AREA_1','AGWU_SQFT_1','RATIO_1']

print ('Second Level')

SecAreabySeq = Ag_Mesh_df.sort(['AGWU_SQFT'],ascending=False).groupby(['SEQNUM'], as_index=False).nth(1)
SecAreabySeq.columns=['SEQNUM','PERMIT_NO_2','APP_NO_2','ACRES_SERVED_2','GIS_AREA_2','AGWU_SQFT_2','RATIO_2']

print ('Third Level')

ThrdAreabySeq = Ag_Mesh_df.sort(['AGWU_SQFT'],ascending=False).groupby(['SEQNUM'], as_index=False).nth(2)
ThrdAreabySeq.columns=['SEQNUM','PERMIT_NO_3','APP_NO_3','ACRES_SERVED_3','GIS_AREA_3','AGWU_SQFT_3','RATIO_3']

print ('Merging area summaries')
#----------------------------------------------------------------------------------------------------------
#   Merge dataframes by SEQNUM
#----------------------------------------------------------------------------------------------------------
Top2AreabySeq = pd.merge(maxAreabySeq, SecAreabySeq, how='left', on=['SEQNUM'])
Top3AreabySeq = pd.merge(Top2AreabySeq, ThrdAreabySeq, how='left', on=['SEQNUM'])

#----------------------------------------------------------------------------------------------------------
#   Merge results and modelMesh dataframes to Add row and column attributes back in
#----------------------------------------------------------------------------------------------------------
Top3AreabySeq = pd.merge(MM_df, Top3AreabySeq, how='right', on=['SEQNUM'])

print('Exporting results')
#----------------------------------------------------------------------------------------------------------
#   Export to csv file
#----------------------------------------------------------------------------------------------------------
Agcsv = workdir + "/predomAgWUROCOwRatioV2.csv"
Top3AreabySeq.to_csv(Agcsv,index=False)
pdomAg = Myworkspace + "/PredomAg_WUv2"
arcpy.CopyRows_management(Agcsv, pdomAg)
