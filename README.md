# Claude-in-hoshino
适用hoshino bot的claude for slack转接插件。使用slack频道内at对话方式和claude对话交互。claude的api对一般用户来说获取难度还是大了点.jpg


主要移植自[LucentQQBot](https://github.com/BlackPinkiller/LucentQQBot)by @Lucent, edited by @空白 @Tasse @BlackPinkiller。感谢各位大佬。
因为chatgpt的插件已经不少了就只把claude的部分摘出来了。


之前写了一半基础功能能用了就放下了一直没写完，等到想起来写完的时候已经是claude多轮监管发癫降智之后的事了.jpg

现在claude for slack虽然不如四五月那会那么好用（意味深）了，不过总归是在gpt和bing之外多个选择.jpg

## 功能

- 可自定义保存加载人格模板（包括初始化模板、对话中维持设定用模板前后缀）

- 双对话模式：

  群聊共用模式：群内所有人共用一个对话上下文

  个人独立模式：群聊中每个人一个独立会话上下文

- 安全模式：本来是用来限制涩涩模板的，但后来发现基本没法限制直接通过对话使用模板，现在已经是鸡肋功能了）

- 会话记录持久化


## 安装

- 首先需要获取能用claude的slack工作区(老区好像还能无限制用，最近新开的区应该只能蹭30天pro试用才能开了,具体方法请自行寻找教程)
- 参考[云仔bot的教程](https://ikechan8370.com/archives/chatgpt-plugin-for-yunzaipei-zhi-slack-claude)创建Slack应用，获取User OAuth Token, 然后再去在slack中获取channel_id和claude_id，具体可参考slack_bot.py中注释说明
- 将相关配置填入config.json
- 安装所需依赖（应该就一个slack_sdk）
- 将本项目放在hoshino/modules/目录下
- 在__bot__.py中添加Claude-in-hoshino


## 使用方法

#### 主要功能指令：

[/claude(对话内容)] 进行对话(回复可能很慢，请耐心等待)

[重置claude会话] 清除当前claude会话并重置claude

[切换claude人格] 切换人格设定

[重置claude人格] 清除当前claude人格，重置为默认claude

[自定义claude人格] 自定义本群临时人格模板，格式为‘初始模板|对话前缀|对话后缀’

[查看claude设置] 查看当前claude设置

===

#### 管理指令：

[新建claude人格] 新建人格设定，格式为‘人格名|初始模板|对话前缀|对话后缀|安全flag(0不安全，1安全)’

[切换claude对话模式] 切换本群对话模式

[切换claude安全模式] 切换本群安全模式（安全模式下仅能选择安全人格模板，不能自定义模板）


## 已知问题

- Claude回复卡Typing时超时设置似乎不起作用，可能是用异步跑同步函数的问题，需要有空了再修一下
