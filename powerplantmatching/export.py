# -*- coding: utf-8 -*-
## Copyright 2015-2016 Fabian Gotzens (FZJ)

## This program is free software; you can redistribute it and/or
## modify it under the terms of the GNU General Public License as
## published by the Free Software Foundation; either version 3 of the
## License, or (at your option) any later version.

## This program is distributed in the hope that it will be useful,
## but WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
## GNU General Public License for more details.

## You should have received a copy of the GNU General Public License
## along with this program.  If not, see <http://www.gnu.org/licenses/>.

## This export script is intented for the users of the VEDA-TIMES modelling
## framework <http://iea-etsap.org/index.php/etsap-tools/data-handling-shells/veda>

import os
import pandas as pd
import numpy as np
import pycountry

from .collection import Carma_ENTSOE_ESE_GEO_OPSD_WEPP_WRI_matched_reduced_VRE
from .heuristics import set_denmark_region_id

def Export_TIMES(df=None, use_scaled_capacity=False, baseyear=2015):

    if df is None:
        df = Carma_ENTSOE_ESE_GEO_OPSD_WEPP_WRI_matched_reduced_VRE()
        if df is None:
            raise RuntimeError("The data to be exported does not yet exist.")
    df = df.copy()

    # Set region via country names by iso3166-2 codes
    if 'Region' not in df:
        pos = [i for i,x in enumerate(df.columns) if x == 'Country'][0]
        df.insert(pos+1, 'Region', np.nan)
    df.loc[:, 'Region'] = df.Country.apply(lambda c: pycountry.countries.get(name=c).alpha2)
    df = set_denmark_region_id(df)
    regions = sorted(set(df.Region))
    if None in regions:
        raise ValueError("There are rows without a valid country identifier "
                         "in the dataframe. Please check!")

    # add column with TIMES-specific type. The pattern is as follows:
    # 'ConELC-' + Set + '_' + Fueltype + '-' Technology
    df.loc[:,'Technology'].fillna('', inplace=True)
    if 'TimesType' not in df:
        pos = [i for i,x in enumerate(df.columns) if x == 'Technology'][0]
        df.insert(pos+1, 'TimesType', np.nan)
    df.loc[:,'TimesType'] = pd.Series('ConELC-' for _ in range(len(df))) +\
          np.where(df.loc[:,'Set'].str.contains('CHP'),'CHP','PP') +\
          '_' + df.loc[:,'Fueltype'].map(fueltype_to_abbrev())
    df.loc[(df['Fueltype']=='Wind') & (df['Technology'].str.contains('offshore', case=False)),'TimesType'] += 'F'
    df.loc[(df['Fueltype']=='Wind') & (df['Technology'].str.contains('offshore', case=False)==False),'TimesType'] += 'N'
    df.loc[(df['Fueltype']=='Solar') & (df['Technology'].str.contains('CSP', case=False)),'TimesType'] += 'CSP'
    df.loc[(df['Fueltype']=='Solar') & (df['Technology'].str.contains('CSP', case=False)==False),'TimesType'] += 'SPV'
    df.loc[(df['Fueltype']=='Natural Gas') & (df['Technology'].str.contains('CCGT', case=False)),'TimesType'] += '-CCGT'       
    df.loc[(df['Fueltype']=='Natural Gas') & (df['Technology'].str.contains('CCGT', case=False)==False)\
           & (df['Technology'].str.contains('OCGT', case=False)),'TimesType'] += '-OCGT'
    df.loc[(df['Fueltype']=='Natural Gas') & (df['Technology'].str.contains('CCGT', case=False)==False)\
           & (df['Technology'].str.contains('OCGT', case=False)==False),'TimesType'] += '-ST'
    df.loc[(df['Fueltype']=='Hydro') & (df['Technology'].str.contains('pumped storage', case=False)),'TimesType'] += '-PST'
    df.loc[(df['Fueltype']=='Hydro') & (df['Technology'].str.contains('run-of-river', case=False))\
           & (df['Technology'].str.contains('pumped storage', case=False)==False),'TimesType'] += '-ROR'
    df.loc[(df['Fueltype']=='Hydro') & (df['Technology'].str.contains('run-of-river', case=False)==False)\
           & (df['Technology'].str.contains('pumped storage', case=False)==False),'TimesType'] += '-STO'
           
    if None in set(df.TimesType):
        raise ValueError("There are rows without a valid TIMES-Type identifier "
                         "in the dataframe. Please check!")

    # add column with technical lifetime
    if 'Life' not in df:
        pos = [i for i,x in enumerate(df.columns) if x == 'YearCommissioned'][0]
        df.insert(pos+1, 'Life', np.nan)
    df.loc[:, 'Life'] = df.TimesType.map(timestype_to_life())
    if df.Life.isnull().any():
        raise ValueError("There are rows without a given lifetime in the "
                         "dataframe. Please check!")

    # add column with decommissioning year
    if 'YearDecommissioned' not in df:
        pos = [i for i,x in enumerate(df.columns) if x == 'Life'][0]
        df.insert(pos+1, 'YearDecommissioned', np.nan)
    df.loc[:, 'YearDecommissioned'] = df.loc[:,'YearCommissioned'] + df.loc[:, 'Life']

    # Now create empty export dataframe with headers
    columns = ['Attribute','*Unit','LimType','Year']
    columns.extend(regions)
    columns.append('Pset_Pn')

    # Loop stepwise through technologies, years and countries
    df_exp = pd.DataFrame(columns=columns)
    cap_column='Scaled Capacity' if use_scaled_capacity else 'Capacity'
    row = 0
    for tt, df_tt in df.groupby('TimesType'):
        for yr in range(baseyear, 2055, 5):
            df_exp.loc[row,'Year'] = yr
            data_regions = df_tt.groupby('Region')
            for reg in regions:
                if reg in data_regions.groups:
                    ct_group = data_regions.get_group(reg)
                    # Here all matched units existing in baseyear are being filtered
                    if yr==baseyear:
                        series = ct_group.apply(lambda x: x[cap_column] \
                            if yr >= x['YearCommissioned']
                            else 0, axis=1)
                    # Here all matched units in yr which are not decommissioned yet, are being filtered
                    elif yr>baseyear:
                        series = ct_group.apply(lambda x: x[cap_column] \
                            if yr >= x['YearCommissioned'] and yr <= x['YearDecommissioned']
                            else 0, axis=1)
                    else:
                        raise ValueError('loop yr({}) below baseyear({})'.format(yr,baseyear))
                    # Divide the sum by 1000 (MW->GW) and write into the export dataframe
                    df_exp.loc[row, reg] = series.sum()/1000.0
                else:
                    df_exp.loc[row, reg] = 0.0
            df_exp.loc[row, 'Pset_Pn'] = tt
            row += 1
    df_exp.loc[:, 'Attribute'] = 'STOCK'
    df_exp.loc[:, '*Unit'] = 'GW'
    df_exp.loc[:, 'LimType'] = 'FX'

    # Write resulting dataframe to file
    outfn = os.path.join(os.path.dirname(__file__),'data','out','Export_Stock_TIMES.xlsx')
    df_exp.to_excel(outfn)
    return df_exp


def fueltype_to_abbrev():
    """
    Returns the fueltype-specific abbreviation.
    """
    data = {'Bioenergy':'BIO',
            'Geothermal':'GEO',
            'Hard Coal':'COA',
            'Hydro':'HYD',
            'Lignite':'LIG',
            'Natural Gas':'NG',
            'Nuclear':'NUC',
            'Oil':'OIL',
            'Other':'OTH',
            'Solar':'', # DO NOT delete this entry!
            'Waste':'WST',
            'Wind':'WO'}
    return data


def timestype_to_life():
    """
    Returns the timestype-specific technical lifetime.
    """
    data = {'ConELC-PP_COA':45,
            'ConELC-PP_LIG':45,
            'ConELC-PP_NG-OCGT':40,
            'ConELC-PP_NG-ST':40,
            'ConELC-PP_NG-CCGT':40,
            'ConELC-PP_OIL':40,
            'ConELC-PP_NUC':50,
            'ConELC-PP_BIO':25,
            'ConELC-PP_HYD-ROR':200,  # According to Anna-Kriek Riekkolas comment, 
            'ConELC-PP_HYD-STO':200,  # these will not retire after 75-100 years,
            'ConELC-PP_HYD-PST':200,  # but exist much longer which retrofit costs.
            'ConELC-PP_WON':25,
            'ConELC-PP_WOF':25,
            'ConELC-PP_SPV':30,
            'ConELC-PP_CSP':30,
            'ConELC-PP_WST':30,
            'ConELC-PP_SYN':5,
            'ConELC-PP_CAES':40,
            'ConELC-PP_GEO':30,
            'ConELC-PP_OTH':5,
            'ConELC-CHP_COA':45,
            'ConELC-CHP_LIG':45,
            'ConELC-CHP_NG-OCGT':40,
            'ConELC-CHP_NG-ST':40,
            'ConELC-CHP_NG-CCGT':40,
            'ConELC-CHP_OIL':40,
            'ConELC-CHP_BIO':25,
            'ConELC-CHP_WST':30,
            'ConELC-CHP_SYN':5,
            'ConELC-CHP_GEO':30,
            'ConELC-CHP_OTH':5,
            }
    return data