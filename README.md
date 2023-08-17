# 目的
在iKow-on-wechat,chatgpt-on-wechat项目中，作为插件，用于保存聊天记录到数据库中（sqlite3)

# 试用场景
目前是在微信公众号下面使用过。

# 使用步骤
1 进入管理员模式:
```
#auth password
```
如果没设置管理员密码，启动程序时会在输出信息中提示临时密码，否则设置 config.json 中Godcmd下 password
2 安装插件
```
#installp https://github.com/akun-y/plugin_chat2db.git
```
3 查看插件安装结果
```
#scanp
```
4 启动插件
```
#enablep Chat2db
```
5 停止插件
```
#disablep Chat2db
```
6 卸载插件
```
#uninstallp Chat2db
```


# 验证结果
