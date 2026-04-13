# DiAi Trader

- 自选8

- 股指期货16

- ETF 20 (4美 + 4全球 + 4HK + 4国债  + 4指数)

- A50

- 上证50

  

# 1.数据处理

./data文件夹

修改tushare文件权限：

> sudo chmod 666 /Users/apple/tk.csv

## 1.1 SSE-50日线下载

> sudo python 1.daily_get_price_tushare.py 

# 2.智能体部署

> sudo python start_mcp_services



> sudo python main_client.py configs/astock_config_day.json  

Support specifying configuration file through command line arguments

Usage: python livebaseagent_config.py [config_path]

Example: python livebaseagent_config.py configs/my_config.json

# 3.web-ui部署



```
cd docs
python -m http.server 8888
```

# 4 关于更新后的GUI如何操作

## 4.1 操作gui的前提
请先在控制台运行以下代码:
```
cd docs
python  bs_server.py
```
这将打开一个小型服务器,为gui操作提供接口服务

## 4.2 标的管理
>[标的管理] 中的所有操作都是对 ./data/stocks.json的操作
##### 1 . 新增组: 
  点击新增组按钮呼出卡片,按要求填写股票代码即可(ETF类别请在填写组名称时加上"ETF"标识,例如: ETF_25 , MY_ETF等)
##### 2 . 恢复默认:
 点击此按钮可将现有标的替换为默认标的(此操作不可逆):
 即将
 >./data/stocks.json

替换为
 >./data/stocks_ori.json

 的内容

**⚠️ 注意：** 编辑标的后,请点击[保存]按钮,右下角弹出保存成功提示后,系统对应配置文件才会更新
 ##### 3 . 下载数据:
 点击[下载数据]按钮,系统将执行:
 >./data/1.get_price_tushare

 自动下载所有标的的股票数据

 
 ## 4.3 智能体管理
 >[智能体管理] 中的所有操作都是对 ./config/astock_config_day.json的操作
##### 1 . 新增智能体: 
点击此按钮呼出卡片,可在此填写对应信息以新增智能体
##### 2 . 启用/禁用智能体: 
点击智能体卡片上的对应按钮,即可进行启用/禁用切换
##### 3 . 删除智能体: 
点击智能体卡片上的[删除]按钮,即可删除该智能体
##### 4 . 编辑运行规则: 
点击[编辑运行规则]按钮,呼出卡片进行对交易规则的编辑. 

**⚠️ 注意：** [编辑运行规则] 中的Ashare_symbols（股票组名）,必须是 
>./data/stocks.json

内已有的股票组名

**⚠️ 注意：** 与[标的管理]相同,在完成以上操作后,请点击[保存配置]按钮,确保右下角弹出[配置保存成功]的提示

##### 5 . 运行: 
点击[运行]按钮,系统将依次执行:
```
python mcp_services_start.py                                  #启动mcp服务器
python main_client.py configs/astock_config_day.json          #启动交易主逻辑
```

