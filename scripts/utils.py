import pickle
import datetime
import pandas as pd
import numpy as np
import requests
import os
import zipfile
from datetime import datetime
import shutil
import re
import glob
from typing import Tuple
from math import ceil


def load_data(fpath):
    df = pd.read_parquet(fpath)
    df.target = series2date(df.target)
    return df


def series2date(series):
    """
    Check dtype of pd.Series, convert to datetime.date
    series: pandas Series with dates in format "yyyy-mm-dd"
    """
    """if isinstance(series[0], str):
        series = series.apply(datetime.datetime.strptime, args=['%Y-%m-%d']).dt.date
    elif isinstance(series[0], datetime.datetime):
        series = series.apply(pd.Timestamp.date)"""
    #if isinstance(series[0], str) or isinstance(series[0], datetime.datetime):
    series = series.astype(np.datetime64)
    return series


def load_results_file(filepath):
    """
    Loads pickled results as DataFrame, converts date columns
    Expects columns [refdate, team, model, target, metric_1,... metric_n]
    filepath: str, path to file
    """
    if filepath[-4:] == ".csv":
        df = pd.read_csv(filepath)
    else:
        try:
            with open(filepath, "rb") as fp:
                df = pickle.load(fp)
        except:
            df = pd.read_pickle(filepath, compression="gzip")

    if isinstance(df, list):
        df = pd.DataFrame(df[1:] if len(df) > 1 else [], columns=df[0])  # expects header in first row

    if len(df):
        df.target = series2date(df.target)
        df.refdate = series2date(df.refdate)

    return df


def load_results(results_dir="../results", submissions_dir="../submissions") -> pd.DataFrame:

    # glob search results dir
    files = glob.glob(f"{results_dir}/*.csv")

    dfs = []
    for f in files:
        try:
            # res_team_model_locationtype_predvariable_enum.csv
            _, team, model, location_type, pred_variable, _ = f.split("_")  # unpacking might not be possible
        except:
            continue

        # check for existence of submission of that team model
        if not os.path.isdir(os.path.join(submissions_dir, team)) :
            print(f"there are no submissions for team {team}")
            continue
        if not len(glob.glob(os.path.join(submissions_dir, team, "*")+f"{'_'.join([model, location_type, pred_variable])}.parquet")):
            print(f"there are no submissions for team {team} with model {model}")
            continue

        subset_df = pd.read_csv(f)
        subset_df.target = series2date(subset_df.target)
        subset_df.refdate = series2date(subset_df.refdate)
        # add columns from file name (team, model, location_type, pred_variable
        # concat/hstack would be faster, but not sure if I used integer index of columns somewhere, so order might matter
        subset_df.insert(1, "team", subset_df.shape[0] * [team])
        subset_df.insert(2, "model", subset_df.shape[0] * [model])
        subset_df.insert(3, "location_type", subset_df.shape[0] * [location_type])
        subset_df.insert(4, "pred_variable", subset_df.shape[0] * [pred_variable])

        dfs.append(subset_df)

    output = pd.concat(dfs)
    if isinstance(output.columns, pd.core.indexes.multi.MultiIndex):
        output.columns = output.columns.get_level_values(0)
    return output


def pickle_results(filepath, obj):
    """
    Saves list to binary file; If obj is DataFrame, converts it to list with header in first row
    filepath: str; where to write file to
    obj: list-like or DataFrame
    """
    #if isinstance(obj, pd.DataFrame):
    #    header = list(obj.columns)
    #    obj = [header] + obj.values.tolist()
    if isinstance(obj, list):
        obj = pd.DataFrame(obj[1:], columns=obj[0])


    #with open(filepath, "wb") as fp:
    #    pickle.dump(obj, fp)

    obj.to_pickle(filepath, compression="gzip")


def get_date_range(start_date_str, days=28):
    """
    Get datetime.date objects of start and end day in 28 day interval.
    start_date_str: string of start date, i.e. '2022-10-10'
    return 2tuple of datetime.date
    """
    start_date = np.datetime64(start_date_str)

    end_date = start_date + np.timedelta64(days - 1, "D")  # first date already counts

    return start_date, end_date


def reset_results_file(fpath="results.pickle"):
    empty = [["refdate", "team", "model", "location_type", "pred_variable", "target", "location",
              "rmse", "wis", "dispersion", "underprediction", "overprediction", "mae", "mda",
              "within_50", "within_80", "within_95"]]
    pickle_results(fpath, empty)


def get_opendata(refdate: str) -> pd.DataFrame:
    """
    Retrieve COVID 7-day incidence on German district level for a given reference date.
    Data source is RKI OpenData repository:
    https://github.com/robert-koch-institut/COVID-19_7-Tage-Inzidenz_in_Deutschland
    """
    # assert refdate is yyyy-mm-dd
    assert len(refdate) == 10 and refdate[4] == '-' and refdate[7] == '-', "refdate should be in the format yyyy-mm-dd"
    # assert refdate is valid date. i.e. not 2022-09-35
    try:
        datetime.strptime(refdate, '%Y-%m-%d')
    except ValueError:
        raise ValueError("refdate is not a valid date")

    refdate_min = '2022-09-30'  # oldest available release
    assert datetime.strptime(refdate, '%Y-%m-%d') >= datetime.strptime(refdate_min, '%Y-%m-%d'),\
        f"refdate should be greater than or equal to {refdate_min}"

    success, retries = False, 0
    while not success or retries == 100:
        # download data
        url = f"https://github.com/robert-koch-institut/COVID-19_7-Tage-Inzidenz_in_Deutschland/archive/refs/tags/{refdate}.zip"
        response = requests.get(url)
        if response.status_code != 200:
            print(f"Failed to download data for {refdate}")
            refdate = str(np.datetime64(refdate) - np.timedelta64(1, "D"))  # try previous day
            retries += 1
            # 404: https://codeload.github.com/robert-koch-institut/COVID-19_7-Tage-Inzidenz_in_Deutschland/zip/refs/tags/2022-11-06
        else:
            success = True

    # save the zip file
    filename = f"{refdate}.zip"
    with open(filename, "wb") as f:
        f.write(response.content)

    # unzip the file
    with zipfile.ZipFile(filename, "r") as zip_ref:
        zip_ref.extractall()

    # delete the zip file
    os.remove(filename)

    dir_path = f"COVID-19_7-Tage-Inzidenz_in_Deutschland-{refdate}"
    fname = "COVID-19-Faelle_7-Tage-Inzidenz_Landkreise.csv"

    df = pd.read_csv(os.path.join(dir_path, fname))  # load into memory

    shutil.rmtree(dir_path)  # clean up

    # reformat data
    # open data columns:
    #       ['Meldedatum', 'Landkreis_id', 'Bevoelkerung', 'Faelle_gesamt',
    #        'Faelle_neu', 'Faelle_7-Tage', 'Inzidenz_7-Tage']

    # repo data columns: ['location', 'target', 'value']
    df_conform = pd.DataFrame(np.zeros([df.shape[0], 3]), columns=['location', 'target', 'value'])
    df_conform['location'] = df['Landkreis_id']
    df_conform['target'] = df['Meldedatum'].astype(np.datetime64)  # TODO perhabs keep as str
    df_conform['value'] = df['Inzidenz_7-Tage'].astype(np.float16)
    #  recalculate incidence?? do we really need more than 1 decimal? nope!

    return df_conform


def calculate_7day_incidence(df: pd.DataFrame) -> pd.DataFrame:
    # Sort dataframe by date
    df = df.sort_values(by='date')

    # Compute rolling sum of cases over the last 7 days for each district
    df['cases_last_7_days'] = df.groupby('district')['cases'].rolling(window=7).sum().reset_index(0, drop=True)

    # Compute 7-day incidence
    df['7_day_incidence'] = (df['cases_last_7_days'] / df['population_size']) * 100000

    return df


def date_is_sunday(date_str: str) -> bool:
    # date_str = '2022-02-27'

    # Convert the date string to a datetime object
    date_obj = datetime.strptime(date_str, '%Y-%m-%d')

    # Check if the day of the week is Sunday (0 = Monday, 1 = Tuesday, ..., 6 = Sunday)
    return date_obj.weekday() == 6


def greater_date(date1: str, date2: str) -> bool:
    return datetime.strptime(date1,  '%Y-%m-%d') > datetime.strptime(date2,  '%Y-%m-%d')


def smaller_date(date1: str, date2: str) -> bool:
    return datetime.strptime(date1,  '%Y-%m-%d') < datetime.strptime(date2,  '%Y-%m-%d')


def filter_last_weeks(df: pd.DataFrame, n: int = 6, date_col: str = "refdate") -> pd.DataFrame:
    today = np.datetime64('today')

    if not np.issubdtype(df[date_col].dtype, np.datetime64):
        df[date_col] = df[date_col].astype(np.datetime64)

    # Filter the dataframe to include only rows with dates within the last n weeks
    n_weeks_ago = today - np.timedelta64(n, 'W')

    return df[df[date_col] < n_weeks_ago]


def filesize_mb(filepath):
    fstats = os.stat(filepath)  # os.path.getsize(path)
    return fstats.st_size / (1024 * 1024)


def get_cutoffs(asize, msize):
    times = ceil(asize / msize)
    return [(t * msize) / asize for t in range(times)]


def cutoff_to_slices(df, cutoffs):
    n = len(cutoffs)
    cutoffs.append(1)  # guarantees that the last row index is always accounted for
    slices = []
    for i in range(n):
        slice_start, slice_end = int(df.shape[0] * cutoffs[i]), int(df.shape[0] * cutoffs[i+1])
        # print(slice_start, slice_end)
        slices.append(df.iloc[slice_start:slice_end, :])

    return slices


def df_to_split_files(df, save_path, max_size_mb=45):

    path, basename, ending = separate_path(save_path)

    # let's try saving file first, because we don't know compression rate
    first_file = f"{path}/{basename}_{1}{ending}"

    df.to_csv(first_file, index=False, float_format='%.2f')
    full_size = filesize_mb(first_file)
    if full_size <= max_size_mb:
        return

    cutoffs = get_cutoffs(full_size, max_size_mb)
    slices = cutoff_to_slices(df, cutoffs)

    for i, s in enumerate(slices):
        s.to_csv(f"{path}/{basename}_{i+1}{ending}", index=False, float_format='%.2f')


def separate_path(fpath: str) -> Tuple[str, str, str]:
    """ Separates file path into directory path, file name (without trailing number) and file extension """

    directory_path, file_name_with_ext = os.path.split(fpath)
    file_name, file_extension = os.path.splitext(file_name_with_ext)

    """if "_" in file_name:
        fn_split = file_name.split("_")
        file_name = "_".join(fn_split[:-1]) # removes trailing number"""

    return directory_path, file_name, file_extension


if __name__ == "__main__":

    #df = get_opendata("2022-09-30")
    #print(df)

    res = load_results("../results", "../submissions")

    print(res.head())

    print(res.shape)
    # groupby model, team, model, location_type, variable
    grouping_columns = ["team", "model", "location_type", "pred_variable"]
    grouped = res.groupby(grouping_columns)
    for model_info, model_results in grouped:
        #print(group.loc[:, [col for col in group.columns.to_list() if col not in grouping_columns]])
        tmp_df = model_results.loc[:, [col for col in model_results.columns.to_list() if col not in grouping_columns]]
        # using group.columns.difference(grouping_columns) results in alphabetical ordering; undesired
        df_to_split_files(tmp_df, f"../results/res_{'_'.join(model_info)}.csv")
