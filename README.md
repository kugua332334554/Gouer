# Gouer
Gouer 是一个全功能群管。

<img width="1940" height="734" alt="QQ_1785390490894" src="https://github.com/user-attachments/assets/e906598f-5695-4a13-9ec1-b83448012d00" />


# 项目说明

前往 https://github.com/kugua332334554/Gouer-Admin-Server 查看 管理员服务器项目

前往 https://github.com/kugua332334554/Gouer-Admin 查看VUE管理员前端

# 部署教程

1.准备环境

1.1 安装Python 3.10-3.12

1.2 创建空数据库 记录root用户及密码

1.3 上传源码 创建虚拟环境

1.4 前往 https://t.me/BotFather 创建您的Bot



2.开始部署

2.1 pip install -r requirements.txt 执行安装依赖包

2.2 编辑.env

2.3 按照 https://github.com/helloxz/nsfw 步骤部署NSFW检查服务

2.4 安装ffmpeg用于视频抽帧，具体教程见 https://github.com/0voice/ffmpeg_develop_doc/blob/main/Linux%E4%B8%8A%E7%9A%84ffmpeg%E5%AE%8C%E5%85%A8%E4%BD%BF%E7%94%A8%E6%8C%87%E5%8D%97.md

2.5 部署查ID模块 https://github.com/kugua332334554/Gouer-Chaid


3.运行项目

3.1 python main.py 或者 python3 main.py 启动项目，数据库表结构自动初始化。



至此 Bot 启动完毕。
