# coding: utf-8


############################################
## Load Packages Used
############################################

# built-in package
import os
import sys

sys.path.append('/Users/chenshan/google_driver/github/ipython-notebook-spark/spark-1.6.0-bin-cdh4/spark-1.6.0-bin-cdh4/python')
sys.path.append('/Users/chenshan/google_driver/github/ipython-notebook-spark/spark-1.6.0-bin-cdh4/spark-1.6.0-bin-cdh4/python/lib/py4j-0.9-src.zip')

import json
import time
import socket
import operator
import itertools
import ConfigParser
import datetime as dt

# third-party package
import pandas as pd
from matplotlib import pylab
import matplotlib.pyplot as plt

import sklearn
import sklearn.preprocessing

import numpy as np
import scipy as sp
import seaborn

import pyspark
from pyspark import SparkContext, SparkConf
from pyspark.sql import SQLContext, HiveContext, Row
from pyspark.storagelevel import StorageLevel
from pyspark.streaming import StreamingContext

import market_api


LOCAL_STORE_PATH = "./logs"
APP_STORE_PATH = "./static"


df_today_share = None
today_length_share = None
rdd_history = None


def create_sc():
    sc_conf = SparkConf()
    sc_conf.setAppName("finance-similarity-app")
    sc_conf.setMaster('spark://10.21.208.21:7077')
    sc_conf.set('spark.executor.memory', '2g')
    sc_conf.set('spark.executor.cores', '4')
    sc_conf.set('spark.cores.max', '40')
    sc_conf.set('spark.logConf', True)
    print sc_conf.getAll()

    sc = None
    try:
        sc.stop()
        sc = SparkContext(conf=sc_conf)
    except:
        sc = SparkContext(conf=sc_conf)

    return sc


def minute_bar_today(trade_date, pre_trade_date, ticker="000001.XSHG"):
    pre_close = market_api.MktIdxdGet(tradeDate=pre_trade_date.replace('-', ''), ticker=ticker[:6])
    df = market_api.MktBarRTIntraDayGet(ticker=ticker)
    df['ratio'] = df.closePrice / pre_close - 1
    
    return df[['ticker', 'barTime', 'closePrice', 'ratio']]


def minute_bar_today_demo(trade_date, pre_trade_date, ticker="000001.XSHG"):
    pre_close = market_api.MktIdxdGetDemo(tradeDate=pre_trade_date.replace('-', ''), ticker=ticker[:6])
    df = market_api.MktBarRTIntraDayGetDemo(ticker=ticker)
    df['ratio'] = df.closePrice / pre_close - 1
    
    return df[['ticker', 'barTime', 'closePrice', 'ratio']]


# ### 相似度算法
def cal_minute_bar_similarity(line_data):
    """计算相似度
    
    line_data format: file_path, json_data
    
    指标：
        1. 偏离值绝对值
        2. 偏离值方差
        3. 偏离值绝对值 - 归一化后
        4. 偏离值方差 - 归一化后
    
    Return:
        square diff and var diff of two lines.
        [diff_square, diff_var, (line_path)]
        [diff_square_normalized, diff_var_normalized, (line_path)]
    """
    tmp = pd.DataFrame()
    
    import sklearn.preprocessing
    scaler = sklearn.preprocessing.MinMaxScaler()
    
    today_data = pd.DataFrame.from_dict(json.loads(df_today_share.value))
    today_data_length = today_length_share.value
    line_path, line_df = line_data

    line_df = pd.DataFrame.from_dict(json.loads(line_df))
    line_df.sort(columns=['barTime'], ascending=True, inplace=True)
    
    tmp['first'] = list(today_data[: today_data_length]['ratio'])
    tmp['second'] = list(line_df[: today_data_length]['ratio'])
    
    _first, _second = list(tmp['first']), list(tmp['second'])
    tmp['first_normalized'] = list(scaler.fit_transform(np.array(_first)))
    tmp['second_normalized'] = list(scaler.fit_transform(np.array(_second)))
    
    tmp['diff'] = tmp['first'] - tmp['second']
    tmp['diff_normalized'] = tmp['first_normalized'] - tmp['second_normalized']
    
    diff_square = sum(tmp['diff'] ** 2)
    diff_square_normalized = sum(tmp['diff_normalized'] ** 2)
    
    diff_var = float(tmp['diff'].var())
    diff_var_normalized = float(tmp['diff_normalized'].var())
    res_square = [round(diff_square, 5), round(diff_square_normalized, 5), (line_path)]
    res_var = [round(diff_var, 5), round(diff_var_normalized, 5), (line_path)]

    return res_square + res_var


# ### 武器库
def build_similarity_report(rdd_similarity):
    """构造相似度报表
    """
    res = rdd_similarity.collect()
    res_df = pd.DataFrame.from_records(res)
    res_df.columns = [u'差值平方', u'归一化后差值平方', u'路径', u'方差', u'归一化后方差', u'p']
    
    return res_df[[u'差值平方', u'归一化后差值平方', u'路径', u'方差', u'归一化后方差']]


def get_similarity_data(similarity, number=50):
    """获取最相似的线
    """
    df = similarity.sort(columns=[u'差值平方'], ascending=True)
    most_similary = list(df[ : number][u'路径'])
    
    rdd_most_similary = rdd_history.filter(lambda x : x[0] in most_similary).collect()
    
    return rdd_most_similary


def draw_similarity(df_today, similarity_data, minute_bar_length=90):
    res = pd.DataFrame()
    df_today = pd.DataFrame.from_dict(json.loads(df_today))
    
    columns = []
    for line_tuple in similarity_data:
        line_id, line_data = line_tuple
        line_id = line_id[-25 : -5]
        line_data = pd.DataFrame.from_dict(json.loads(line_data))
        res[line_id] = line_data['ratio']
        
        if 'minute' not in res :
            res['minute'] = line_data['barTime']  
        columns.append(line_id)
    
    res['fitting'] = res[columns].sum(axis=1) / len(columns)
    res.sort(columns=['minute'], ascending=True, inplace=True)
    res['today_line'] = list(df_today['ratio']) + [None] * (241 - len(df_today))
    
    ### plot 
    ax = res.plot(x='minute', y=columns, figsize=(20, 13), legend=False, title=u'Minute Bar Prediction')
    res.plot(y=['today_line'], ax=ax, linewidth=5, style='b')
    res.plot(y=['fitting'], ax=ax, linewidth=4, style='-y')
    ax.vlines(x=minute_bar_length, ymin=-0.02, ymax=0.02, linestyles='dashed')
    ax.set_axis_bgcolor('white')
    ax.grid(color='gray', alpha=0.2, axis='y')
    
    ### plot area
    avg_line = res['fitting']
    avg_line = list(avg_line)[minute_bar_length : ]
    for line in columns:
        predict_line = res[line]
        predict_line = list(predict_line)[minute_bar_length : ]
        ax.fill_between(range(minute_bar_length, 241), avg_line, predict_line, alpha=0.1, color='r')
    
    ### store data on dist
    current_time = dt.datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    res.to_json(LOCAL_STORE_PATH + '/data-{}.json'.format(current_time))
    res.to_json(LOCAL_STORE_PATH + '/latest.json'.format(current_time))

    fig = ax.get_figure()
    fig.savefig(LOCAL_STORE_PATH + '/plot-{}.png'.format(current_time))
    fig.savefig(LOCAL_STORE_PATH + '/latest.png'.format(current_time))
    fig.savefig(APP_STORE_PATH + '/latest.png'.format(current_time))


def pipeline():
    global df_today_share
    global today_length_share
    global rdd_history

    now = dt.datetime.now()
    bar_time = '{}:{}'.format(now.hour, now.minute)
    print '###Loat history data {} ...'.format(time.ctime())
    # ### 加载，分发数据
    rdd_history = sc.wholeTextFiles('hdfs://10.21.208.21:8020/user/mercury/minute_bar', minPartitions=80)  \
                    .setName('index_minute_bar')       \
                    .cache()

    while bar_time < '15:00':
        print '###Start Prediction on {} ...'.format(time.ctime())

        df_today = minute_bar_today('20160804', '20160803', ticker="000001.XSHG") 
        df_today_share = sc.broadcast(df_today)
        # df_today_share = sc.broadcast(120)
        today_length = len(df_today)
        today_length_share = sc.broadcast(today_length)

        ### do the calculation
        rdd_similarity = rdd_history.map(cal_minute_bar_similarity).setName("similariy")                               .cache()
        res_df = build_similarity_report(rdd_similarity)
        similarity_data = get_similarity_data(res_df, 40)
        res = draw_similarity(df_today, similarity_data, minute_bar_length=today_length_share.value)
        
        print '###Done Prediction on {} ...'.format(time.ctime())
        time.sleep(65)
        now = dt.datetime.now()
        bar_time = '{}:{}'.format(now.hour, now.minute)
        
    sc.stop()


def demo():
    global df_today_share
    global today_length_share
    global rdd_history

    print '###Loat history data {} ...'.format(time.ctime())
    ### 创建 sc 
    sc = create_sc()

    ### 加载，分发数据
    rdd_history = sc.wholeTextFiles('hdfs://10.21.208.21:8020/user/mercury/minute_bar', minPartitions=80)  \
                    .setName('index_minute_bar')       \
                    .cache()

    today_length = 120

    while today_length < 241:
        print '###Start Prediction on ...'.format()

        df_today = minute_bar_today_demo('20160702', '20160701', ticker="000001.XSHG") 
        df_today = df_today[: today_length].to_json()
        df_today_share = sc.broadcast(df_today)
        today_length_share = sc.broadcast(today_length)

        ### do the calculation
        rdd_similarity = rdd_history.map(cal_minute_bar_similarity).setName("similariy").cache()

        res_df = build_similarity_report(rdd_similarity)
        similarity_data = get_similarity_data(res_df, 40)
        res = draw_similarity(df_today, similarity_data, minute_bar_length=today_length_share.value)
        
        print '###Done Prediction on  ...'.format()
        time.sleep(65)
        today_length += 1
        
    sc.stop()


if __name__ == '__main__':
    demo()

