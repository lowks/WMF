from cu import *
from models import *
import numpy as np
import glob
from mpl_toolkits.basemap import Basemap, addcyclic, shiftgrid, cm
import pylab as pl
import scipy.ndimage as nd
from netCDF4 import Dataset  
import osgeo.ogr, osgeo.osr
import gdal
from scipy.spatial import Delaunay
import os
import pylab as pl
import pandas as pd
import datetime as datetime
from matplotlib.colors import LogNorm

#-----------------------------------------------------------------------
#Lectura de informacion y mapas 
#-----------------------------------------------------------------------
def read_map_raster(ruta_map,isDEMorDIR=False,dxp=None):
	'Funcion: read_map\n'\
	'Descripcion: Lee un mapa raster soportado por GDAL.\n'\
	'Parametros Obligatorios:.\n'\
	'	-ruta_map: Ruta donde se encuentra el mpaa.\n'\
	'Parametros Opcionales:.\n'\
	'	-isDEMorDIR: Pasa las propiedades de los mapas al modulo cuencas \n'\
	'		escrito en fortran \n'\
	'Retorno:.\n'\
	'	Si no es DEM o DIR retorna todas las propieades del elemento en un vector.\n'\
	'		En el siguiente orden: ncols,nrows,xll,yll,dx,nodata.\n'\
	'	Si es DEM o DIR le pasa las propieades a cuencas para el posterior trazado.\n'\
	'		de cuencas y tramos.\n' \
    #Abre el mapa
	direction=gdal.Open(ruta_map)
	#lee la informacion del mapa
	ncols=direction.RasterXSize
	nrows=direction.RasterYSize
	banda=direction.GetRasterBand(1)
	noData=banda.GetNoDataValue()
	geoT=direction.GetGeoTransform()
	dx=geoT[1]
	xll=geoT[0]; yll=geoT[3]-nrows*dx
	#lee el mapa
	Mapa=direction.ReadAsArray()
	direction.FlushCache()
	del direction
	if isDEMorDIR==True:
		cu.ncols=ncols
		cu.nrows=nrows
		cu.nodata=noData
		cu.dx=dx
		cu.xll=xll
		cu.yll=yll
		if dxp==None:
			cu.dxp=30.0
		else:
			cu.dxp=dxp
		return Mapa.T
	else:
		return Mapa.T,[ncols,nrows,xll,yll,dx,noData]

def OCG_param(alfa=[0.75,0.2],sigma=[0.0,0.225,0.225],
	c1=5.54,k=0.5,fhi=0.95,Omega=0.13,pend=None,area=None,
	):
	'Funcion: OCG_param\n'\
	'Descripcion: Calcula los parametros de la onda cinematica.\n'\
	'geomorfologica (Velez, 2001).\n'\
	'Parametros Opcionales:.\n'\
	'	-isDEMorDIR: Pasa las propiedades de los mapas al modulo cuencas \n'\
	'		escrito en fortran \n'\
	'Retorno:.\n'\
	'	Parametros: B, w1, w2 y w3.\n'\
	'		si se entregan los mapas de pend, aacum entrega h_coef(4,:) .\n' \
	'		se asume que w1 corresponde a h_exp(4,:) .\n' \
	#Calcula los parametros de la ecuacion de onda cinematica 
	B = Omega*(c1*k**(alfa[0]-alfa[1]))**((2.0/3.0)-alfa[1])
	eB=1.0/(1+alfa[1]*((2/3.0)-sigma[1]))
	w1=((2/3.0)-sigma[1])*(1.0-alfa[1])*eB
	w2=(1+alfa[1]*((2/3.0)-sigma[1]))/(fhi*((2/3.0)-sigma[1])*(alfa[0]-alfa[1])+sigma[0])
	w2=(fhi*(0.667-sigma[1])*(alfa[1]-alfa[0])+sigma[0])*eB
	w3=(0.5-sigma[2])*eB
	B=B**(-eB)
	if pend<>None and area<>None:
		var = B*(pend**w2)*(area**w3)
		return var,w1
	else:
		return B,w1,w2,w3		

def PotCritica(S,D,te = 0.056):
    ti = te * (D*1600*9.8)
    return ti *(8.2* (((ti/(1000*9.8*S))/D)**(1.0/6.0)) * np.sqrt(ti/1000.0))/9800.0
	
#-----------------------------------------------------------------------
#Clase de cuencas
#-----------------------------------------------------------------------

class Basin:
	
	#------------------------------------------------------
	# Subrutinas de trazado de cuenca y obtencion de parametros
	#------------------------------------------------------
	#Inicia la cuenca
	def __init__(self,lat,lon,DEM,DIR,name='NaN',stream=None,
		umbral=1000):
		'Descripcion: Inicia la variable de la cuenca, y la traza \n'\
		'	obtiene las propiedades basicas de la cuenca. \n'\
		'\n'\
		'Parametros\n'\
		'----------\n'\
		'self : Inicia las variables vacias.\n'\
		'lat : Coordenada en X de la salida de la cuenca.\n'\
		'lon : Coordenada en Y de la salida de la cuenca.\n'\
		'name : Nombre con el que se va a conocer la cuenca.\n'\
		'stream : Opcional, si se coloca, las coordenadas no tienen.\n'\
		'	que ser exactas, estas se van a corregir para ubicarse.\n'\
		'	en el punto mas cercano dentro de la corriente, este.\n'\
		'	debe ser un objeto del tipo stream.\n'\
		'umbral : umbral minimo para la creacion de cauce (defecto =1000).\n'\
		'\n'\
		'Retornos\n'\
		'----------\n'\
		'self : Con las variables iniciadas.\n'\
		#Si se entrega cauce corrige coordenadas
		if stream<>None:
			error=[]
			for i in stream.structure.T:
				error.append( np.sqrt((lat-i[0])**2+(lon-i[1])**2) )
			loc=np.argmin(error)
			lat=stream.structure[0,loc]
			lon=stream.structure[1,loc]
		#copia la direccion de los mapas de DEM y DIR, para no llamarlos mas
		self.name=name
		self.DEM=DEM
		self.DIR=DIR
		#Traza la cuenca 
		self.ncells = cu.basin_find(lat,lon,DIR,
			cu.ncols,cu.nrows)
		self.structure = cu.basin_cut(self.ncells)
		self.umbral = umbral
	#Parametros Geomorfologicos
	def GetGeo_Parameters(self):
		'Descripcion: Obtiene los parametros geomorfologicos de la cuenca \n'\
		'	y los tiempos de concentracion calculados por diferentes metodologias. \n'\
		'\n'\
		'Parametros\n'\
		'----------\n'\
		'\n'\
		'Retornos\n'\
		'----------\n'\
		'GeoParameters : Parametros de la cuenca calculados.\n'\
		'Tc :  Tiempo de concentracion calculado para la cuenca.\n'\
		#Calcula lo que se necesita para sacar los parametros
		acum,longCeld,S0,Elev=cu.basin_basics(self.structure,
			self.DEM,self.DIR,cu.ncols,cu.nrows,self.ncells)
		slope=cu.basin_arc_slope(self.structure,self.DEM,self.ncells,
			cu.ncols,cu.nrows)
		Lpma,puntto=cu.basin_findlong(self.structure,self.ncells)
		cauce,nodos,trazado,n_nodos,n_cauce = cu.basin_stream_nod(self.structure,
			acum,self.umbral,self.ncells)
		ppal_nceldas,punto = cu.basin_ppalstream_find(self.structure,
			nodos,longCeld,Elev,self.ncells)
		ppal = cu.basin_ppalstream_cut(ppal_nceldas,self.ncells)
		self.hipso_main,self.hipso_basin=cu.basin_ppal_hipsometric(
			self.structure,Elev,punto,30,ppal_nceldas,self.ncells)
		self.main_stream=ppal
		nperim = cu.basin_perim_find(self.structure,self.ncells)
		#Obtiene los parametros 
		Area=(self.ncells*cu.dxp**2)/1e6
		Perim=nperim*cu.dxp/1000.0
		Lcau=ppal[1,-1]/1000.0
		Scau=np.polyfit(ppal[1,::-1],ppal[0],1)[0]*100
		Scue=slope.mean()*100
		Hmin=Elev[-1]; Hmax=Elev[puntto]; Hmean=Elev.mean()
		HCmax=Elev[punto]
		#Genera un diccionario con las propiedades de la cuenca 
		self.GeoParameters={'Area[km2]': Area,
			'Perimetro[km]':Perim,
			'Pend Cauce [%]':Scau,
			'Long Cau [km]': Lcau,
			'Pend Cuenca [%]': Scue,
			'Long Cuenca [km]': Lpma,
			'Hmax [m]':Hmax,
			'Hmin [m]':Hmin,
			'Hmean [m]':Hmean,
			'H Cauce Max [m]':HCmax}
		#Calcula los tiempos de concentracion
		Tiempos={}
		Tc=0.3*(Lcau/(Scue**0.25))**0.75
		Tiempos.update({'US Army': Tc})
		Tc=0.3*(Lcau/((Hmax-Hmin)/Lcau)**0.25)**0.75
		Tiempos.update({'Direccion Carreteras Espana': Tc})
		Tc=(0.02*(Lpma*1000.0)**0.77)/((Scau/100.0)**0.385)/60.0
		Tiempos.update({'Kiprich': Tc})
		Tc=8.157*((Area**0.316)/(((Scau*100)**0.17)*Scue**0.565))
		Tiempos.update({'Campo y Munera': Tc})
		Tc=(4*np.sqrt(Area)+1.5*Lcau)/(0.8*np.sqrt(Hmean))
		Tiempos.update({'Giandotti':Tc})
		Tc=0.4623*(Lcau**0.5)*((Scue/100.0)**(-0.25))
		Tiempos.update({'John Stone': Tc})
		Tc=(Lcau/Area)*(np.sqrt(Area)/Scau)
		Tiempos.update({'Ventura': Tc})
		Tc=0.3*(Lcau/(((HCmax-Hmin)/Lcau)*100)**0.25)**0.75
		Tiempos.update({'Temez': Tc})
		self.Tc=Tiempos
	#Parametros por mapas (distribuidos)
	def GetGeo_Cell_Basics(self):
		'Descripcion: Obtiene: area acumulada, long de celdas, Pendiente \n'\
		'	y Elevacion en cada elemento de la cuenca. \n'\
		'\n'\
		'Parametros\n'\
		'----------\n'\
		'self : no necesita nada es autocontenido.\n'\
		'\n'\
		'Retornos\n'\
		'----------\n'\
		'CellAcum : Cantidad de celdas acumuladas.\n'\
		'CellLong : Longitud de cada una de las celdas [mts].\n'\
		'CellSlope : Pendiente de cada una de las celdas [y/x].\n'\
		'CellHeight : Elevacion de cada una de las celdas [m.s.n.m].\n'\
		#obtiene los parametros basicos por celdas
		acum,longCeld,S0,Elev=cu.basin_basics(self.structure,
			self.DEM,self.DIR,cu.ncols,cu.nrows,self.ncells)
		self.CellAcum=acum; self.CellLong=longCeld
		self.CellSlope=S0; self.CellHeight=Elev
		#Obtiene el canal en la cuenca 
		self.CellCauce = np.zeros(self.ncells)
		self.CellCauce[self.CellAcum>self.umbral]=1
	def GetGeo_IsoChrones(self,Tc):
		'Descripcion: Obtiene el tiempo de viaje aproximado de cada  \n'\
		'	celda a la salida de la cuenca, para eso usa el tiempo de . \n'\
		'	concentracion obtenido por la funcion GetGeo_Parameters . \n'\
		'\n'\
		'Parametros\n'\
		'----------\n'\
		'self : no necesita nada es autocontenido.\n'\
		'Tc : Valor escalar de tiempo de concentracion.\n'\
		'\n'\
		'Retornos\n'\
		'----------\n'\
		'isochrones : Mapa de viaje de cada celda a la salida [hrs].\n'\
		#Calcula la velocidad adecuada para que el tiempo coincida
		acum,longCeld,S0,Elev=cu.basin_basics(self.structure,
			self.DEM,self.DIR,cu.ncols,cu.nrows,self.ncells)
		rangos=[50,25,1]
		for i in range(8):			
			times=[]
			for r in rangos:
				speed = r*S0**(0.5)
				time = cu.basin_time_to_out(self.structure,
					longCeld,speed,self.ncells)/3600.0
				times.append(time[np.isfinite(time)].mean())
			for j in range(2):
				if Tc>times[j] and Tc<times[j+1]:
					rangos=[rangos[j],(rangos[j]+rangos[j+1])/2.0,
						rangos[j+1]]
		#Calcula los intervalos 
		intervalos=np.arange(0,np.ceil(time.max())+1,
			np.ceil(time.max())/10.0)
		timeC=np.zeros(self.ncells)
		tamano=[]
		for i,j in zip(intervalos[:-1],intervalos[1:]):
			timeC[(time>=i) & (time<j)]=(i+j)/2.0
			tamano.append(timeC[timeC==(i+j)/2.0].shape[0])
		tamano=np.array(tamano)
		aportes=(tamano/float(self.ncells))*((self.ncells*cu.dxp**2)/1e6)	
		self.CellTravelTime=time
	def GetGeo_HAND(self,umbral=1000):
		'Descripcion: Calcula Height Above the Nearest Drainage (HAND) \n'\
		'	y Horizontal Distance to the Nearest Drainage (HDND) (Renno, 2008). \n'\
		'\n'\
		'Parametros\n'\
		'----------\n'\
		'self : no necesita nada es autocontenido.\n'\
		'umbral : cantidad minima de celdas para el trazado.\n'\
		'\n'\
		'Retornos\n'\
		'----------\n'\
		'HAND : Elevacion sobre la red de drenaje cercana [mts].\n'\
		'HDND : Distancia horizontal a la red de drenaje cercana [mts].\n'\
		#obtiene los parametros basicos por celdas
		acum,longCeld,S0,Elev=cu.basin_basics(self.structure,
			self.DEM,self.DIR,cu.ncols,cu.nrows,self.ncells)		
		cauce,nodos,trazado,n_nodos,n_cauce = cu.basin_stream_nod(
			self.structure,acum,umbral,self.ncells)
		hand,hdnd,hand_destiny = cu.geo_hand(self.structure,Elev,longCeld,cauce,self.ncells)
		handC=np.zeros(self.ncells)
		handC[hand<5.3]=1
		handC[(hand>=5.3) & (hand<=15.0)]=2
		handC[(hand>15.0) & (S0<0.076)]=4
		handC[(hand>15.0) & (S0>=0.076)]=3	
		self.CellHAND=hand
		self.CellHAND_class=handC
		self.CellHDND=hdnd
		self.CellHAND_drainCell=hand_destiny
					
	#------------------------------------------------------
	# Trabajo con mapas externos y variables fisicas
	#------------------------------------------------------
	def Transform_Map2Basin(self,Map,MapProp):
		'Descripcion: A partir de un mapa leido obtiene un vector \n'\
		'	con la forma de la cuenca, el cual luego puede ser agregado a esta. \n'\
		'\n'\
		'Parametros\n'\
		'----------\n'\
		'self : Inicia las variables vacias.\n'\
		'Map : Matriz con la informacion del mapa.\n'\
		'MapProp : Propiedades del mapa.\n'\
		'\n'\
		'Retornos\n'\
		'----------\n'\
		'vecMap : Vector conla informacion del mapa al interio de la cuenca.\n'\
		#Comienza le codifgo 
		vec = cu.basin_map2basin(self.structure,
			Map,MapProp[2],MapProp[3],MapProp[4],
			cu.nodata,
			'fill_mean',
			self.ncells,
			MapProp[0],MapProp[1])
		return vec
	def Transform_Hills2Basin(self,HillsMap):
		'Descripcion: A partir de un vector con propiedades de las laderas\n'\
		'	obtiene un vector con las propiedades por celda, ojo estas \n'\
		'	quedan con las formas de las laderas y la variable queda agregada. \n'\
		'\n'\
		'Parametros\n'\
		'----------\n'\
		'self : la cuenca misma.\n'\
		'MapHills : Vector con las variables por laderas [nhills].\n'\
		'\n'\
		'Retornos\n'\
		'----------\n'\
		'CellMap : Vector con la variable agregada por laderas, pero .\n'\
		'	pasada a celdas.\n'\
		#Genera el mapa de basin vacio
		CellMap = np.ones(self.ncells)
		#itera por la cantidad de elementos y les va asignando
		for i,k in enumerate(HillsMap):
			CellMap[self.hills_own==i+1] = k
		return CellMap
	def Transform_Basin2Hills(self,CellMap,mask=None):
		'Descripcion: A partir de un vector tipo Basin obtiene un\n'\
		'	vector del tipo laderas, en donde las propiedades se \n'\
		'	agregan para cada ladera. \n'\
		'\n'\
		'Parametros\n'\
		'----------\n'\
		'self : la cuenca misma.\n'\
		'CellMap : Vector con las propiedades por celdas [ncells].\n'\
		'\n'\
		'Retornos\n'\
		'----------\n'\
		'HillsMap : Vector con las prop agregadas a laderas .\n'\
		#Si hay mascara la tiene en cuenta
		if mask<>None:
			Ma = np.zeros(self.ncells)
			if type(mask) is float or type(mask) is int:
				Ma[CellMap==mask] = 1
			elif type(mask) is np.ndarray:
				Ma = np.copy(mask)
		else:
			Ma = np.ones(self.ncells)
		#Pasa el mapa de celdas a mapa de laderas		
		HillsMap = cu.basin_subbasin_map2subbasin(self.hills_own,
			CellMap, self.nhills, self.ncells, Ma)
		return HillsMap
	#------------------------------------------------------
	# Trabajo con datos puntuales puntos 
	#------------------------------------------------------
	
	#------------------------------------------------------
	# Caudales de largo plazo y regionalizacion
	#------------------------------------------------------
	#Caudal de largo plazo 
	def GetQ_Balance(self,Precipitation, Tipo_ETR = 1, mu_choud = 1.37):
		'Descripcion: Calcula el caudal medio por balance de largo plazo\n'\
		'	para ello requiere conocer la precipitacion y el metodo de\n'\
		'	estimacion de la evaporacion.\n'\
		'\n'\
		'Parametros\n'\
		'----------\n'\
		'self : no necesita nada es autocontenido.\n'\
		'Precipitation : Cantidad anual de lluvia, escalar o vector.\n'\
		'Elevacion : Elevacion en cada punto de la cuenca.\n'\
		'Tipo_ETR : Tipo de ecuacion para calcular la evaporacion.\n'\
		'	-1. Turc.\n'\
		'	-2. Cenicafe Budyko.\n'\
		'	-3. Choundry.\n'\
		'	Defecto: 1.\n'\
		'\n'\
		'Retornos\n'\
		'----------\n'\
		'CellQmed : Caudal medio calculado para toda la cuenca.\n'\
		'CellETR : ETR calculada para toda la cuenca.\n'\
		#Calcula las propiedades de la cuenca 
		self.GetGeo_Cell_Basics()
		#Determina si la precipitacion es un vector o un escalar 
		if type(Precipitation) is int or type(Precipitation) is float:
			precip = np.ones(self.ncells)*Precipitation
		elif type(Precipitation) is np.ndarray:
			precip = Precipitation
		#Calcula el qmed
		self.CellQmed,self.CellETR = cu.basin_qmed(
			self.CellAcum,
			self.CellHeight,
			precip,
			self.ncells,
			etr_type=Tipo_ETR,
			mu_choud = mu_choud)

	#Caudales extremos
	#def GetQ_Max(self,Precipitation):
	#def GetQ_Min(self,Precipitation):

	#------------------------------------------------------
	# Guardado shp de cuencas y redes hidricas 
	#------------------------------------------------------
	def Save_Net2Map(self,ruta,dx=30.0,umbral=1000,
		qmed=None,Dict=None,DriverFormat='ESRI Shapefile',
		EPSG=4326):
		'Descripcion: Guarda la red hidrica simulada de la cuenca en .shp \n'\
		'	Puede contener un diccionario con propiedades de la red hidrica. \n'\
		'\n'\
		'Parametros\n'\
		'----------\n'\
		'self : no necesita nada es autocontenido.\n'\
		'ruta : Lugar y nombre donde se va a guardar la red hidrica.\n'\
		'dx : Longitud de las celdas planas.\n'\
		'umbral : cantidad de celdas necesarias para corriente.\n'\
		'qmed : caudal medio calculado por alguna metodologia.\n'\
		'Dict : Diccionario con parametros de la red hidrica que se quieren imprimir.\n'\
		'DriverFormat : nombre del tipo de archivo vectorial de salida (ver OsGeo).\n'\
		'EPSG : Codigo de proyeccion utilizada para los datos, defecto WGS84.\n'\
		'\n'\
		'Retornos\n'\
		'----------\n'\
		'Escribe un archivo vectorial con la estructura de la red hidrica y sus propiedades.\n'\
		#division de la cuenca 
		acum=cu.basin_acum(self.structure,self.ncells)
		cauce,nod_f,n_nodos=cu.basin_subbasin_nod(self.structure,acum,umbral,self.ncells)
		sub_pert,sub_basin=cu.basin_subbasin_find(self.structure,nod_f,n_nodos,self.ncells)
		sub_basins=cu.basin_subbasin_cut(n_nodos)
		sub_horton,nod_hort=cu.basin_subbasin_horton(sub_basins,self.ncells,n_nodos)
		sub_hort=cu.basin_subbasin_find(self.structure,nod_hort,n_nodos,self.ncells)[0]
		cauceHorton=sub_hort*cauce
		#Obtiene la red en manera vectorial 
		nodos = cu.basin_stream_nod(self.structure,acum,umbral,self.ncells)[1]
		netsize = cu.basin_netxy_find(self.structure,nodos,cauceHorton,self.ncells)
		net=cu.basin_netxy_cut(netsize,self.ncells)
		if qmed<>None:
			netsize = cu.basin_netxy_find(self.structure,nodos,cauce*qmed,self.ncells)
			netQmed=cu.basin_netxy_cut(netsize,self.ncells)
		cortes=np.where(net[0,:]==-999)
		cortes=cortes[0].tolist()
		cortes.insert(0,0)
		#Escribe el shp de la red hidrica
		if ruta.endswith('.shp')==False:
			ruta=ruta+'.shp'
		spatialReference = osgeo.osr.SpatialReference()
		spatialReference.ImportFromEPSG(EPSG)
		driver = osgeo.ogr.GetDriverByName(DriverFormat)
		if os.path.exists(ruta):
		     driver.DeleteDataSource(ruta)
		shapeData = driver.CreateDataSource(ruta)
		layer = shapeData.CreateLayer('layer1', spatialReference, osgeo.ogr.wkbLineString)
		layerDefinition = layer.GetLayerDefn()
		new_field=osgeo.ogr.FieldDefn('Long[km]',osgeo.ogr.OFTReal)
		layer.CreateField(new_field)
		new_field=osgeo.ogr.FieldDefn('Horton',osgeo.ogr.OFTInteger)
		layer.CreateField(new_field)
		if qmed<>None:
			new_field=osgeo.ogr.FieldDefn('Qmed[m3s]',osgeo.ogr.OFTReal)
			layer.CreateField(new_field)
		if Dict<>None:
			if type(Dict==dict):
				netDict=[]
				for k in Dict.keys():
					new_field=osgeo.ogr.FieldDefn(k[:10],osgeo.ogr.OFTReal)
					layer.CreateField(new_field)
					netsizeT = cu.basin_netxy_find(self.structure,nodos,cauce*Dict[k],self.ncells)
					netDict.append(cu.basin_netxy_cut(netsize,self.ncells))
		#Para cada tramo
		featureFID=0
		for i,j in zip(cortes[:-1],cortes[1:]):
			line = osgeo.ogr.Geometry(osgeo.ogr.wkbLineString)
			for x,y in zip(net[1,i+1:j],net[2,i+1:j]):
				line.AddPoint_2D(float(x),float(y))		
			feature = osgeo.ogr.Feature(layerDefinition)
			feature.SetGeometry(line)
			feature.SetFID(0)
			feature.SetField('Long[km]',(net[1,i+1:j].size*dx)/1000.0)
			feature.SetField('Horton',int(net[0,i+1]))
			if qmed<>None:	
				feature.SetField('Qmed[m3s]',float(netQmed[0,j-1]))
			if Dict<>None:
				if type(Dict==dict):
					for n,k in zip(netDict,Dict.keys()):					
						feature.SetField(k[:10],float(n[0,j-1]))
			#featureFID+=1
			layer.CreateFeature(feature)
			line.Destroy()
			feature.Destroy()
		shapeData.Destroy()
	def Save_Basin2Map(self,ruta,dx=30.0,Param={},
		DriverFormat='ESRI Shapefile',EPSG=4326):
		'Descripcion: Guarda un archivo vectorial de la cuenca en .shp \n'\
		'	Puede contener un diccionario con propiedades. \n'\
		'\n'\
		'Parametros\n'\
		'----------\n'\
		'self : no necesita nada es autocontenido.\n'\
		'ruta : Lugar y nombre donde se va a guardar la cuenca.\n'\
		'dx : Longitud de las celdas planas.\n'\
		'DriverFormat : nombre del tipo de archivo vectorial de salida (ver OsGeo).\n'\
		'EPSG : Codigo de proyeccion utilizada para los datos, defecto WGS84.\n'\
		'\n'\
		'Retornos\n'\
		'----------\n'\
		'Escribe un archivo vectorial de la cuenca.\n'\
		#Obtiene el perimetro de la cuenca 
		nperim = cu.basin_perim_find(self.structure,self.ncells)
		basinPerim=cu.basin_perim_cut(nperim)
		#Param,Tc=basin_Tc(basin.structure,DEM,DIR,cu.dxp,basin.ncells,cu.ncols,cu.nrows)
		#Construye el shp 
		if ruta.endswith('.shp')==False:
			ruta=ruta+'.shp'
		#Genera el shapefile
		spatialReference = osgeo.osr.SpatialReference()
		spatialReference.ImportFromEPSG(EPSG)
		driver = osgeo.ogr.GetDriverByName(DriverFormat)
		if os.path.exists(ruta):
		     driver.DeleteDataSource(ruta)
		shapeData = driver.CreateDataSource(ruta)
		layer = shapeData.CreateLayer('layer1', spatialReference, osgeo.ogr.wkbPolygon)
		layerDefinition = layer.GetLayerDefn()
		for p in Param.keys():
			new_field=osgeo.ogr.FieldDefn(p[:p.index('[')].strip()[:10],osgeo.ogr.OFTReal)
			layer.CreateField(new_field)
		#Calcula el tamano de la muestra
		ring = osgeo.ogr.Geometry(osgeo.ogr.wkbLinearRing)
		for i in basinPerim.T:
			ring.AddPoint(x=float(i[0]),y=float(i[1]))
		poly=osgeo.ogr.Geometry(osgeo.ogr.wkbPolygon)
		poly.AddGeometry(ring)
		feature = osgeo.ogr.Feature(layerDefinition)
		feature.SetGeometry(poly)
		feature.SetFID(0)
		for p in Param.keys():		
			feature.SetField(p[:p.index('[')].strip()[:10],float("%.2f" % Param[p]))
		layer.CreateFeature(feature)
		poly.Destroy()
		ring.Destroy()
		feature.Destroy()
		shapeData.Destroy()

	#------------------------------------------------------
	# Graficas de la cuenca
	#------------------------------------------------------
	def Plot_basin_fast(self,vec,Min=None,
		Max=None,ruta=None,mostrar='si',barra='si',figsize=(10,8),
		ZeroAsNaN = 'no'):
	    #Plotea en la terminal como mapa un vector de la cuenca
	    'Funcion: write_proyect_int_ext\n'\
	    'Descripcion: Genera un plot del mapa entrgeado.\n'\
	    'del mismo en forma de mapa \n'\
	    'Parametros Obligatorios:.\n'\
	    '	-basin: Vector con la forma de la cuenca.\n'\
	    '	-vec: Vector con los valores a plotear.\n'\
	    'Parametros Opcionales:.\n'\
	    '	-Min: Valor minimo del plot, determina el rango de colores.\n'\
	    '	-Max: Valor maximo del plot, determina el rango de colores.\n'\
	    '	-ruta: Ruta en la cual se guarda la grafica.\n'\
	    '	-mostrar: Muestra o no la grafica, defecto: si.\n'\
	    '	-barra: Muestra o no la barra de colores, defecto: si.\n'\
	    '	-figsize: tamano de la ventana donde se muestra la cuenca.\n'\
	    '	-ZeroAsNaN: Convierte los valores de cero en NaN.\n'\
	    'Retorno:.\n'\
	    '	Actualizacion del binario .int\n'\
	    #Delimita el mapa
	    Mcols,Mrows=cu.basin_2map_find(self.structure,self.ncells)
	    m,mxll,myll=cu.basin_2map(self.structure,vec,Mcols,Mrows,
			self.ncells)
	    m[m==cu.nodata]=np.nan
	    if ZeroAsNaN is 'si': m[m==0.0] = np.nan
	    #Genera la figura 
	    fig = pl.figure(figsize = figsize)
	    if Min<>None and Max<>None:
			pl.imshow(m.T,norm=LogNorm(vmin=Min,vmax=Max))
	    else:
			pl.imshow(m.T)
	    if barra=='si':
			pl.colorbar()
	    if ruta<>None and type(ruta)==str:
			pl.savefig(ruta,bbox_inches='tight')
	    if mostrar=='si':
			pl.show()
		

class SimuBasin(Basin):
	
	def __init__(self,lat,lon,DEM,DIR,name='NaN',stream=None,umbral=500,
		noData=-999,modelType='cells',SimSed='no',SimSlides='no',dt=60,
		SaveStorage='no',SaveSpeed='no'):
		'Descripcion: Inicia un objeto para simulacion \n'\
		'	el objeto tiene las propieades de una cuenca con. \n'\
		'	la diferencia de que inicia las variables requeridas. \n'\
		'	para simular. \n'\
		'\n'\
		'Parametros\n'\
		'----------\n'\
		'self : Inicia las variables vacias.\n'\
		'lat : Coordenada en X de la salida de la cuenca.\n'\
		'lon : Coordenada en Y de la salida de la cuenca.\n'\
		'name : Nombre con el que se va a conocer la cuenca.\n'\
		'	(defecto = NaN).\n'\
		'stream : Opcional, si se coloca, las coordenadas no tienen.\n'\
		'	que ser exactas, estas se van a corregir para ubicarse.\n'\
		'	en el punto mas cercano dentro de la corriente, este.\n'\
		'	debe ser un objeto del tipo stream.\n'\
		'umbral : Cantidad minima de celdas para la creacion de cauces.\n'\
		'	(defecto = 500 ).\n'\
		'noData : Valor correspondiente a valores sin dato (defecto = -999).\n'\
		'modelType : Tipo de modelo, por celdas o por laderas (defecto = cells).\n'\
		'	opciones: .\n'\
		'		cells => modela por celdas.\n'\
		'		hills => modela por laderas.\n'\
		'SimSed : Simula si, o no simula sedimentos no.\n'\
		'SimSlides : Simula si, o no simula deslizamientos no.\n'\
		'dt : Tamano del intervlao de tiempo en que trabaj el modelo (defecto=60seg) [secs].\n'\
		'SaveStorage : Guarda o no el almacenamiento.\n'\
		'SaveSpeed : Guarda o no mapas de velocidad.\n'\
		'\n'\
		'Retornos\n'\
		'----------\n'\
		'self : Con las variables iniciadas.\n'\
		#Si se entrega cauce corrige coordenadas
		if stream<>None:
			error=[]
			for i in stream.structure.T:
				error.append( np.sqrt((lat-i[0])**2+(lon-i[1])**2) )
			loc=np.argmin(error)
			lat=stream.structure[0,loc]
			lon=stream.structure[1,loc]
		#copia la direccion de los mapas de DEM y DIR, para no llamarlos mas
		self.name=name
		self.DEM=DEM
		self.DIR=DIR
		self.modelType=modelType
		self.nodata=noData
		self.umbral = umbral
		#Traza la cuenca 
		self.ncells = cu.basin_find(lat,lon,DIR,
			cu.ncols,cu.nrows)
		self.structure = cu.basin_cut(self.ncells)
		#traza las sub-cuencas
		acum=cu.basin_acum(self.structure,self.ncells)
		cauce,nodos,self.nhills = cu.basin_subbasin_nod(self.structure
			,acum,umbral,self.ncells)
		self.hills_own,sub_basin = cu.basin_subbasin_find(self.structure,
			nodos,self.nhills,self.ncells)
		self.hills = cu.basin_subbasin_cut(self.nhills)
		models.drena=self.structure		
		#Determina la cantidad de celdas para alojar
		if modelType=='cells':
			N=self.ncells
		elif modelType=='hills':
			N=self.nhills
		#aloja variables
		models.v_coef = np.ones((4,N))
		models.h_coef = np.ones((4,N))
		models.v_exp = np.ones((4,N))
		models.h_exp = np.ones((4,N))
		models.max_capilar = np.ones((1,N))
		models.max_gravita = np.ones((1,N))
		models.storage = np.zeros((5,N))
		models.dt = dt
		#Define las simulaciones que se van a hacer 
		models.sim_sediments=0
		if SimSed is 'si':
			models.sim_sediments=1
		models.sim_slides=0
		if SimSlides is 'si':
			models.sim_slides=1
		models.save_storage=0
		if SaveStorage is 'si':
			models.save_storage=1
		models.save_speed=0
		if SaveSpeed is 'si':
			models.save_speed=1
			
	#------------------------------------------------------
	# Subrutinas de lluvia, interpolacion, lectura, escritura
	#------------------------------------------------------	
	def rain_interpolate_mit(self,coord,registers,ruta):
		'Descripcion: Interpola la lluvia mediante una malla\n'\
		'	irregular de triangulos, genera campos que son. \n'\
		'	guardados en un binario para luego ser leido por el. \n'\
		'	modelo en el momento de simular. \n'\
		'\n'\
		'Parametros\n'\
		'----------\n'\
		'self : .\n'\
		'coord : Array (2,Ncoord) con las coordenadas de estaciones.\n'\
		'registers : Array (Nest,Nregisters) con los registros de lluvia.\n'\
		'ruta : Ruta con nombre en donde se guardara el binario con.\n'\
		'	la informacion de lluvia.\n'\
		'\n'\
		'Retornos\n'\
		'----------\n'\
		'Guarda el binario, no hay retorno\n'\
		'\n'\
		'Mirar Tambien\n'\
		'----------\n'\
		'rain_interpolate_idw: interpola campos mediante la metodologia idw.\n'\
		'rain_read_bin: Lee binario de registros para ver que tiene.\n'\
		'rain_ncf2bin: Convierte ncf a binario en formato del modelo (para imagenes de radar).\n'\
		#Mira si los registros son un data frame de pandas
		isPandas=False
		if type(registers)==pd.core.frame.DataFrame:
			reg=registers.values.T
			isPandas=True
		else:
			reg=registers
		#inventa estaciones en las esquinas del DEM
		for i,j in zip([0,0,1,1],[0,1,1,0]):
			x=cu.xll+cu.ncols*cu.dx*i
			y=cu.yll+cu.nrows*cu.dx*j
			d=np.sqrt((coord[0,:]-x)**2+(coord[1,:]-y)**2)
			pos=np.argmin(d)
			#Actualiza las coordenadas			
			coord=np.vstack((coord.T,np.array([x,y]))).T			
			#pone lluvia en ese registro 
			reg=np.vstack((reg,reg[pos]))
		#Obtiene las coordenadas de cada celda de la cuenca
		x,y = cu.basin_coordxy(self.structure,self.ncells)
		xy_basin=np.vstack((x,y))	
		#Obtiene la malla irregular 
		TIN_mesh=Delaunay(coord.T)
		TIN_mesh=TIN_mesh.vertices.T+1
		#Obtiene las pertenencias en la cuenca a la malla 
		TIN_perte = models.rain_pre_mit(xy_basin,TIN_mesh,coord,self.ncells,
			TIN_mesh.shape[1],coord.shape[1]) 	 			
		#Genera las interpolaciones para el rango de datos 		
		models.rain_mit(xy_basin,coord,reg,TIN_mesh,
			TIN_perte,ruta,self.ncells,coord.shape[1],
			TIN_mesh.shape[1],reg.shape[1])
		#Guarda un archivo con informacion de la lluvia 
		f=open(ruta[:-3]+'hdr','w')
		f.write('Numero de celdas: %d \n' % self.ncells)
		f.write('Numero de laderas: %d \n' % self.nhills)
		f.write('Numero de registros: %d \n' % reg.shape[1])
		f.write('Tipo de interpolacion: TIN\n')
		f.write('Record, Fecha \n')
		if isPandas:
			dates=registers.index.to_pydatetime()
			for c,d in enumerate(dates):
				f.write('%d, %s \n' % (c,d.strftime('%Y-%m-%d-%H:%M')))
		f.close()
			
	def rain_interpolate_idw(self,coord,registers,ruta,p=1):
		'Descripcion: Interpola la lluvia mediante la metodologia\n'\
		'	del inverso de la distancia ponderado. \n'\
		'\n'\
		'Parametros\n'\
		'----------\n'\
		'self : .\n'\
		'coord : Array (2,Ncoord) con las coordenadas de estaciones.\n'\
		'registers : Array (Nest,Nregisters) con los registros de lluvia.\n'\
		'p :  exponente para la interpolacion de lluvia.\n'\
		'ruta : Ruta con nombre en donde se guardara el binario con.\n'\
		'	la informacion de lluvia.\n'\
		'\n'\
		'Retornos\n'\
		'----------\n'\
		'Guarda el binario, no hay retorno\n'\
		'\n'\
		'Mirar Tambien\n'\
		'----------\n'\
		'rain_interpolate_mit: interpola campos mediante la metodologia idw.\n'\
		'rain_read_bin: Lee binario de registros para ver que tiene.\n'\
		'rain_ncf2bin: Convierte ncf a binario en formato del modelo (para imagenes de radar).\n'\
		#Mira si los registros son un data frame de pandas
		isPandas=False
		if type(registers)==pd.core.frame.DataFrame:
			reg=registers.values.T
			isPandas=True
		else:
			reg=registers
		#Obtiene las coordenadas de cada celda de la cuenca
		x,y = cu.basin_coordxy(self.structure,self.ncells)
		xy_basin=np.vstack((x,y))	
		#Interpola con idw 		
		models.rain_idw(xy_basin,coord,reg,p,ruta,self.ncells,
			coord.shape[1],reg.shape[1])
		#Guarda un archivo con informacion de la lluvia 
		f=open(ruta[:-3]+'hdr','w')
		f.write('Numero de celdas: %d \n' % self.ncells)
		f.write('Numero de laderas: %d \n' % self.nhills)
		f.write('Numero de registros: %d \n' % reg.shape[1])
		f.write('Tipo de interpolacion: IDW, p= %.2f \n' % p)
		f.write('Record, Fecha \n')
		if isPandas:
			dates=registers.index.to_pydatetime()
			for c,d in enumerate(dates):
				f.write('%d, %s \n' % (c,d.strftime('%Y-%m-%d-%H:%M')))
		f.close()
	
	def rain_radar2basin(self):
		return 1
		
	#------------------------------------------------------
	# Subrutinas para preparar modelo 
	#------------------------------------------------------	
	def set_Geomorphology(self,umbrales=[30,500],stream_width=None):
		'Descripcion: calcula las propiedades geomorfologicas necesarias \n'\
		'	para la simulacion. \n'\
		'\n'\
		'Parametros\n'\
		'----------\n'\
		'self : Inicia las variables vacias.\n'\
		'umbrales : Lista con la cantidad de celdas necesarias .\n'\
		'	para que una celda sea: ladera, carcava o cauce .\n'\
		'stream_width = Ancho del canal en cada tramo (opcional).\n'\
		'\n'\
		'Retornos\n'\
		'----------\n'\
		'self : Con las variables geomorfologicas de simulacion iniciadas.\n'\
		'	models.drena : Numero de celda o ladera destino. \n'\
		'	models.nceldas : Numero de celdas o laderas. \n'\
		'	models.unit_type : tipo de celda, en el caso de ladera no aplica.\n'\
		'		1: Celda tipo ladera.\n'\
		'		2: Celda tipo carcava.\n'\
		'		3: Celda tipo cauce.\n'\
		'	models.hill_long : Longitud de la ladera (o celda). \n'\
		'	models.hill_slope : Pendiente de cada ladera (o celda).\n'\
		'	models.stream_long : Longitud de cada tramo de cuace. \n'\
		'	models.stream_slope : Pendiente de cada tramo de cauce. \n'\
		'	models.stream_width : Ancho de cada tramo de cauce. \n'\
		'	models.elem_area : Area de cada celda o ladera. \n'\
		#Obtiene lo basico para luego pasar argumentos
		acum,hill_long,pend,elev = cu.basin_basics(self.structure,
			self.DEM,self.DIR,cu.ncols,cu.nrows,self.ncells)
		#Obtiene parametros para la cuenca como si fuera celdas
		#Obtiene el tipo de celdas
		unit_type = cu.basin_stream_type(self.structure,
			acum,umbrales,len(umbrales),self.ncells)
		#Obtiene la pendiente y la longitud de las corrientes
		cauce,nodos,trazado,n_nodos,n_cauce = cu.basin_stream_nod(
			self.structure,acum,umbrales[1],self.ncells)
		stream_s,stream_l = cu.basin_stream_slope(
			self.structure,elev,hill_long,nodos,n_cauce,self.ncells)
		stream_s[np.isnan(stream_s)]=self.nodata		
		#Obtiene para metros por subn cuencas
		sub_horton,nod_horton = cu.basin_subbasin_horton(self.hills,self.ncells,
			self.hills.shape[1])
		sub_basin_long,max_long,nodo_max_long = cu.basin_subbasin_long(
			self.hills_own,cauce,hill_long,self.hills,
			sub_horton,self.hills.shape[1],self.ncells)
		#Obtiene las propiedades por laderas de los cauces 
		stream_slope,stream_long = cu.basin_subbasin_stream_prop(
			self.hills_own,cauce,hill_long,
			pend,self.hills.shape[1],self.ncells)
		#opbtiene el ancho si noe s dado lo asume igual a uno 
		if stream_width==None:
			stream_width=np.ones(self.ncells)
		#De acuerdo a si el modelo es por laderas o por celdas agrega lass varaibeles 
		if self.modelType=='cells':
			models.drena = np.ones((1,self.ncells))*self.structure
			models.nceldas = self.ncells
			models.unit_type = np.ones((1,self.ncells))*unit_type
			models.hill_long = np.ones((1,self.ncells))*hill_long
			models.hill_slope = np.ones((1,self.ncells))*pend
			models.stream_long = np.ones((1,self.ncells))*hill_long
			models.stream_slope = np.ones((1,self.ncells))*pend
			models.stream_width = np.ones((1,self.ncells))*stream_width
			models.elem_area = np.ones((1,self.ncells))*cu.dxp**2.0
		elif self.modelType=='hills':
			N=self.hills.shape[1]
			models.drena = np.ones((1,N))*self.hills[1]
			models.nceldas = self.hills.shape[1]
			models.unit_type = np.ones((1,N))*np.ones(N)*3
			models.hill_long = np.ones((1,N))*sub_basin_long
			models.hill_slope = np.ones((1,N))*self.Transform_Basin2Hills(pend) 				
			models.stream_long = np.ones((1,N))*stream_long
			models.stream_slope = np.ones((1,N))*stream_slope
			models.stream_width = np.ones((1,N))*cu.basin_subbasin_map2subbasin(
				self.hills_own,stream_width,self.hills.shape[1],self.ncells,self.CellCauce)
			models.elem_area = np.ones((1,N))*np.array([self.hills_own[self.hills_own==i].shape[0] for i in range(1,self.hills.shape[1]+1)])*cu.dxp**2.0			
	def set_speed_type(self,types=np.ones(3)):
		'Descripcion: Especifica el tipo de velocidad a usar en cada \n'\
		'	nivel del modelo. \n'\
		'\n'\
		'Parametros\n'\
		'----------\n'\
		'self : Inicia las variables vacias.\n'\
		'types : tipos de velocidad .\n'\
		'	1. Velocidad tipo embalse lineal, no se especifica h_exp.\n'\
		'	2. Velocidad onda cinematica, se debe especificar h_exp.\n'\
		'\n'\
		'Retornos\n'\
		'----------\n'\
		'self : Con la variable models.speed_type especificada.\n'\
		#Especifica la ecuacion de velocidad a usar en cada nivel del modelo		
		for c,i in enumerate(types):
			if i==1 or i==2:
				models.speed_type[c]=i
			else:
				models.speed_type[c]=1	
	def set_PhysicVariables(self,modelVarName,var,pos,mask=None):
		'Descripcion: Coloca las variables fisicas en el modelo \n'\
		'	Se debe assignarel nombre del tipo de variable, la variable\n'\
		'	y la posicion en que esta va a ser insertada\n'\
		'\n'\
		'Parametros\n'\
		'----------\n'\
		'self : Objeto de la cuenca 2que luego se va a simular.\n'\
		'modelVarName : Nombre de la variable del modelo que se va a incertar.\n'\
		'	- h_coef.\n'\
		'	- h_exp.\n'\
		'	- v_coef.\n'\
		'	- v_exp.\n'\
		'	- max_capilar.\n'\
		'	- Max_gravit.\n'\
		'var : variable que ingresa en el modelo, esta puede ser:.\n'\
		'	- Ruta: una ruta del tipo string.\n'\
		'	- Escalar : Un valor escalar que se asignara a toda la cuenca.\n'\
		'	- Vector : Un vector con la informacion leida (1,ncells).\n'\
		'pos : Posicion de insercion, aplica para : h_coef, v_coef,.\n'\
		'	h_exp, v_exp.\n'\
		'\n'\
		'Retornos\n'\
		'----------\n'\
		'Guarda el binario, no hay retorno\n'\
		'\n'\
		'Mirar Tambien\n'\
		'----------\n'\
		'rain_interpolate_idw: interpola campos mediante la metodologia idw.\n'\
		'rain_read_bin: Lee binario de registros para ver que tiene.\n'\
		'rain_ncf2bin: Convierte ncf a binario en formato del modelo (para imagenes de radar).\n'\

		#Obtiene el vector que va a alojar en el modelo
		isVec=False
		if type(var) is str:
			#Si es un string lee el mapa alojado en esa ruta 
			Map,Pp = read_map_raster(var)
			Vec = self.Transform_Map2Basin(Map,Pp)
			isVec=True
		elif type(var) is int or float:
			Vec = np.ones((1,self.ncells))*var
			isVec=True
		elif type(var) is np.ndarray and var.shape[0] == self.ncells:			
			Vec = var
			isVec=True
		#Si el modelo es tipo ladera agrega la variable 
		if self.modelType is 'hills':
			Vec = self.Transform_Basin2Hills(Vec,mask=mask)
		#finalmente mete la variable en el modelo
		if modelVarName is 'h_coef':
			models.h_coef[pos] = Vec
		elif modelVarName is 'h_exp':
			models.h_exp[pos] = Vec
		elif modelVarName is 'v_coef':
			models.v_coef[pos] = Vec
		elif modelVarName is 'v_exp':
			models.v_exp[pos] = Vec
		elif modelVarName is 'capilar':
			models.max_capilar[0] = Vec
		elif modelVarName is 'gravit':
			models.max_gravita[0] = Vec
	def set_record(self,controlQ=None,controlH=None,saveVec=None):
		'Descripcion: Establece los puntos donde el modelo va  ahacer control\n'\
		'	de los estados de humedad en el suelo y de caudal. \n'\
		'\n'\
		'Parametros\n'\
		'----------\n'\
		'self : Inicia las variables vacias.\n'\
		'controlQ : Vector con los puntos de control para caudal [ncells, o nhills].\n'\
		'controlH : Vector con los puntos de control para humedad [ncells, o nhills].\n'\
		'\n'\
		'Retornos\n'\
		'----------\n'\
		'self : Con la variable models.control y models.control_h especificadas.\n'\
		#Determina en donde hace control de caudal 
		if controlQ <> None:			
			if self.modelType is 'cells':				
				if controlQ.shape[0] == self.ncells:
					models.control = np.ones((1,self.ncells))*controlQ					
			elif self.modelType is 'hills':
				if controlQ.shape[0] == self.nhills:
					models.control = np.ones((1,self.nhills))*controlQ					
		else:
			if self.modelType is 'cells':
				models.control = np.zeros((1,self.ncells))
			elif self.modelType is 'hills':				
				models.control = np.zeros((1,self.nhills))
		models.control[0][-1]=1
		#Determina en donde hace control de humedad
		if controlH <> None:
			if self.modelType is 'cells':
				if controlH.shape[0] == self.ncells:
					models.control_h = np.ones((1,self.ncells))*controlH
			elif self.modelType is 'hills':
				if controlH.shape[0] == self.nhills:
					models.control_h = np.ones((1,self.nhills))*controlH
		else:
			if self.modelType is 'cells':
				models.control_h = np.zeros((1,self.ncells))
			elif self.modelType is 'hills':				
				models.control_h = np.zeros((1,self.nhills))
	def set_storage(self,var,pos):
		'Descripcion: \n'\
		'	Establece el almacenamiento inicial del modelo\n'\
		'	la variable puede ser un valor, una ruta o un vector.\n'\
		'\n'\
		'Parametros\n'\
		'----------\n'\
		'var : Variable conla cual se va a iniciar el almancenamiento.\n'\
		'	- ruta : es una ruta a un archivo binario de almacenamiento.\n'\
		'	- escalar : valor de almacenamiento constate para toda la cuenca.\n'\
		'	- vector : Vector con valores para cadda unidad de la cuenca.\n'\
		'pos : Posicion de insercion,.\n'\
		'	- 0 :  alm cpailar.\n'\
		'	- 1 :  alm superficial.\n'\
		'	- 2 :  alm sub-superficial.\n'\
		'	- 3 :  alm subterráneo.\n'\
		'	- 4 :  alm cauce.\n'\
		'\n'\
		'Retornos\n'\
		'----------\n'\
		'Guarda el binario, no hay retorno\n'\
		'\n'\
		'Mirar Tambien\n'\
		'----------\n'\
		'save_storage(slef,storage).\n'\
		#Determina el tipo de unidades del modelo 
		if self.modelType is 'cells':
			N = self.ncells
		elif self.modelType is 'hills':
			N = self.nhills
		#Obtiene el vector que va a alojar en el modelo
		isVec=False
		if type(var) is str:
			#Si es un string lee el binario de almacenamiento alojado en esa ruta 
			Vec,res = models.read_float_basin(var,pos+1,N)
			isVec=True
		elif type(var) is int or float:
			Vec = np.ones((1,N))*var
			isVec=True
		elif type(var) is np.ndarray and var.shape[0] == N:			
			Vec = var
			isVec=True
		#Aloja ese almacenamiento en la cuenca 
		models.storage[pos] = Vec
		
	#def set_sediments(self,var,varName):
		
		
	#def set_slides(self,var,varName):

	#------------------------------------------------------
	# Ejecucion del modelo
	#------------------------------------------------------	
	def run_shia(self,Calibracion,
		rain_rute, N_intervals, start_point = 1):
		'Descripcion: Ejecuta el modelo una ves este es preparado\n'\
		'	Antes de su ejecucion se deben tener listas todas las . \n'\
		'	variables requeridas . \n'\
		'\n'\
		'Parametros\n'\
		'----------\n'\
		'self : Cuenca a ejecutar con todo listo para ser ejecutada.\n'\
		'Calibracion : Parametros de calibracion del modelo, orden:.\n'\
		'	- Evaporacion.\n'\
		'	- Infiltracion.\n'\
		'	- Percolacion.\n'\
		'	- Perdidas.\n'\
		'	- Vel Superficial .\n'\
		'	- Vel Sub-superficial.\n'\
		'	- Vel Subterranea.\n'\
		'	- Vel Cauce.\n'\
		'	- Max Capilar.\n'\
		'	- Max Gravitacional.\n'\
		'rain_rute : Ruta donde se encuentra el archivo binario de lluvia:.\n'\
		'	generado por rain_interpolate_* o por rain_radar2basin.\n'\
		'N_intervals : Numero de intervalos de tiempo.\n'\
		'start_point : Punto donde comienza a usar registros de lluvia.\n'\
		'	los binarios generados por rain_* generan un archivo de texto.\n'\
		'	que contiene fechas par aayudar a ubicar el punto de inicio deseado.\n'\
		'\n'\
		'Retornos\n'\
		'----------\n'\
		'Qsim : Caudal simulado en los puntos de control.\n'\
		'Hsim : Humedad simulada en los puntos de control.\n'\
		# De acuerdo al tipo de modelo determina la cantidad de elementos
		if self.modelType is 'cells':
			N = self.ncells
		elif self.modelType is 'hills':
			N = self.nhills
		#prepara variables globales
		models.rain_first_point = start_point
		#Prepara terminos para control
		if np.count_nonzero(models.control) is 0 :
			NcontrolQ = 1
		else:
			NcontrolQ = np.count_nonzero(models.control)
		if np.count_nonzero(models.control_h) is 0 :
			NcontrolH = 1
		else:
			NcontrolH = np.count_nonzero(models.control_h)
		# Ejecuta el modelo 
		Qsim,Qsed,Humedad,Balance,Alm = models.shia_v1(
			rain_rute,
			Calibracion,
			N,
			NcontrolQ,
			NcontrolH,
			N_intervals)
		#Retorno de variables de acuerdo a lo simulado 
		Retornos={'Qsim' : Qsim}
		Retornos.update({'Balance' : Balance})
		Retornos.update({'Storage' : Alm})
		if np.count_nonzero(models.control_h)>0:
			Retornos.update({'Humedad' : Humedad})
		if models.sim_sediments is 1:
			Retornos.update({'Sediments' : Qsed})
		return Retornos
		
class Stream:
	#------------------------------------------------------
	# Subrutinas de trazado de corriente y obtencion de parametros
	#------------------------------------------------------
	#Inicia la cuenca
	def __init__(self,lat,lon,DEM,DIR,name='NaN'):
		'Descripcion: Traza un cauce e inicia la variable de este \n'\
		'\n'\
		'Parametros\n'\
		'----------\n'\
		'self : Inicia las variables vacias.\n'\
		'lat : Coordenada en X del punto mas alto del cauce.\n'\
		'lon : Coordenada en Y del punto mas alto del cauce.\n'\
		'\n'\
		'Retornos\n'\
		'----------\n'\
		'self : Con las variables iniciadas y estructura del cauce.\n'\
		#Realiza copia de los mapas y obtiene el cauce
		self.DEM = DEM
		self.DIR = DIR
		self.ncells = cu.stream_find(lat,lon,self.DEM,
			self.DIR,cu.ncols,cu.nrows)
		self.structure = cu.stream_cut(self.ncells)
	#------------------------------------------------------
	# Guardado shp de cauce
	#------------------------------------------------------
	def Save_Stream2Map(self,ruta,DriverFormat='ESRI Shapefile',
		EPSG=4326):
		'Descripcion: Guarda el cauce trazado en un mapa \n'\
		'\n'\
		'Parametros\n'\
		'----------\n'\
		'self : Inicia las variables vacias.\n'\
		'ruta : Nombre del lugar donde se va a guardar el cauce.\n'\
		'DriverFormat : Tipo de mapa vectorial.\n'\
		'EPSG : Codigo de tipo de proyeccion usada (defecto 4326).\n'\
		'\n'\
		'Retornos\n'\
		'----------\n'\
		'Guarda el cauce en el formato especificado.\n'\
		#Escribe el shp del cauce
		if ruta.endswith('.shp')==False:
			ruta=ruta+'.shp'
		spatialReference = osgeo.osr.SpatialReference()
		spatialReference.ImportFromEPSG(EPSG)
		driver = osgeo.ogr.GetDriverByName(DriverFormat)
		if os.path.exists(ruta):
		     driver.DeleteDataSource(ruta)
		shapeData = driver.CreateDataSource(ruta)
		layer = shapeData.CreateLayer('layer1', 
			spatialReference, osgeo.ogr.wkbLineString)
		layerDefinition = layer.GetLayerDefn()
		line = osgeo.ogr.Geometry(osgeo.ogr.wkbLineString)
		for x,y in zip(self.structure[0],self.structure[1]):
			line.AddPoint_2D(float(x),float(y))		
		feature = osgeo.ogr.Feature(layerDefinition)
		feature.SetGeometry(line)
		feature.SetFID(0)
		layer.CreateFeature(feature)
		line.Destroy()
		feature.Destroy()
		shapeData.Destroy()
	#------------------------------------------------------
	# Plot de variables
	#------------------------------------------------------
	def Plot_Profile(self,ruta=None):
		'Descripcion: Grafica el perfil del cauce trazado \n'\
		'\n'\
		'Parametros\n'\
		'----------\n'\
		'self : Inicia las variables vacias.\n'\
		'ruta : Nombre de la imagen si se va a guardar la imagen del cauce.\n'\
		'\n'\
		'Retornos\n'\
		'----------\n'\
		'Guarda el cauce en el formato especificado.\n'\
		#Escribe el shp del cauce
		fig=pl.figure(facecolor='w',edgecolor='w')
		ax=fig.add_subplot(111)
		ax.plot(self.structure[3],self.structure[2],lw=2)
		ax.set_xlabel('Distancia $[mts]$',size=14)
		ax.set_ylabel('Elevacion $[m.s.n.m]$',size=14)
		ax.grid(True)
		if ruta<>None:
			pl.savefig(ruta,bbox_inches='tight')
		pl.show()
	#def Plot_Map(self,ruta=None):