# -*- coding: utf-8 -*-
import json
import os
import traceback
from copy import deepcopy
import re

from .Slack_Bot import midware
from .Slack_Bot import load_sessions, pop_sessions, load_auth


from hoshino import Service, priv
from hoshino.util import FreqLimiter
from hoshino.aiorequests import run_sync_func
from hoshino.typing import CQEvent


working_path = os.path.abspath(os.path.realpath(os.path.dirname(__file__)))


def get_config(filename):
    with open(os.path.join(working_path, filename), "r", encoding='utf8') as config_file:
        config = json.load(config_file)
    return config


def save_config(content, filename):
    with open(os.path.join(working_path, filename), 'w', encoding='utf8') as config_file:
        json.dump(content, config_file, ensure_ascii=False, indent=4)


cq_code_pattern = re.compile(r'\[CQ:\w+,.+\]')

sv_help = '''claude for slack对话功能
[/claude (对话内容)] 进行对话(回复可能很慢，请耐心等待)
[重置claude会话] 清除当前claude会话并重置claude
[切换claude人格] 切换人格设定
[重置claude人格] 清除当前claude人格，重置为默认claude
[新建claude人格] 新建人格设定，格式为‘人格名|模板|前缀|后缀|安全’
[自定义claude人格] 自定义临时人格模板，格式为‘模板|前缀|后缀’
[查看claude设置] 查看当前claude设置
[切换claude对话模式] 切换对话模式（群聊共用/个人独立）
[切换claude安全模式] 切换安全模式（不许涩涩）
'''

sv = Service('claude', help_=sv_help, manage_priv=50, enable_on_default=False)

lmt = FreqLimiter(60)
flmt = FreqLimiter(60)

# config_data = dict()
persona_presets = dict()
config_group = dict()

sessions = {}


def reload_config():
    # global config_data
    global persona_presets
    global config_group

    # config_data = get_config('config.json')
    persona_presets = get_config('presets.json')
    config_group = get_config('config_group.json')
    load_auth()
    load_sessions()


reload_config()

# group_mode: 0:个人独立对话, 1:群聊共享对话
# safe_mode: 0:off 1:on
config_group_template = {
    'preset': '',
    'group_mode': 1,
    'safe_mode': 1,
    'user': {}
}

config_user_template = {'preset': ''}


def update_config_group_json(id, key='', value='', user=False):
    global config_group
    if str(id) not in config_group:
        config_group[str(id)] = deepcopy(config_group_template)
    if key:
        if user:
            config_group[str(id)]['user'][key] = value
        else:
            config_group[str(id)][key] = value
    save_config(config_group, 'config_group.json')


def get_sessionid(group_id, user_id):
    m_gid = 'G' + str(group_id)   # G+群号
    m_uid = 'G' + str(group_id) + 'U' + str(user_id)   # G+发言者的qq号
    # 判断对话模式
    if not str(group_id) in config_group:
        update_config_group_json(str(group_id), 'preset', '')
    if config_group[str(group_id)]["group_mode"] != 0:
        sessionid = m_gid  # 获得对话session
    else:
        if user_id not in config_group[str(group_id)]['user']:
            update_config_group_json(
                str(group_id), user_id, {'preset': ''}, True)
        sessionid = m_uid  # 获得对话session
    return sessionid


def charactor_prase(sessionid, pos):
    if 'U' in sessionid:
        chara = config_group[sessionid[1:].split(
            'U')[0]]["user"][sessionid[1:].split('U')[1]]["preset"]
    else:
        chara = config_group[str(sessionid[1:])]["preset"]

    if chara in persona_presets:
        return persona_presets[chara][pos]
    elif len(chara.split('|')) == 3:
        chara_temp = {'init': chara.split('|')[0], 'prefix': chara.split('|')[
            1], 'suffix': chara.split('|')[2]}
        return chara_temp[pos]
    elif chara == '':
        return ''
    else:
        raise 'chara prase error'


async def send_message_to_channel(message_text: str = "", session_id: str = "g01"):
    answer = await run_sync_func(midware, message_text=message_text, session_id=session_id)
    return answer

# default_session_config ={'msg': [{"role": "system", "content": ""}], "character": -3, "safe_mode": 1}

current_key_index = 0


@sv.on_fullmatch(('重载claude配置', '重载cld配置'))
async def reload_auth(bot, ev: CQEvent):
    if not priv.check_priv(ev, priv.SUPERUSER):
        await bot.finish(ev, '此功能仅维护组可用~', at_sender=True)
        return
    reload_config()
    await bot.send(ev, f"已重载claude配置...")


@sv.on_prefix(('/claude', '/cld'))
async def ai_reply(bot, ev: CQEvent):
    try:
        mid = ev.message_id
        group_id = str(ev.group_id)
        user_id = str(ev.user_id)
        msg = ev.message.extract_plain_text().strip()
        prompt = re.sub(cq_code_pattern, '', msg).strip()

        if not prompt:
            await bot.send(ev, f'请在/claude命令后接上你想说的话~', at_sender=True)
            return

        if not lmt.check(group_id):
            await bot.send(ev, f'我还在思考上一个问题，请问完一句再问下一句~', at_sender=True)
            return
        if not priv.check_priv(ev, priv.SUPERUSER):
            if not flmt.check(group_id):
                await bot.send(ev, f'功能冷却中，请{int(flmt.left_time(group_id)) + 1}秒后再来~', at_sender=True)
                return
        lmt.start_cd(group_id, 300)
        flmt.start_cd(group_id)

        sessionid = get_sessionid(group_id, user_id)

        message_edited = charactor_prase(
            sessionid, 'prefix') + msg + charactor_prase(sessionid, 'suffix')

        await bot.send(ev, "少女思考中...")
        ans = await send_message_to_channel(message_text=message_edited, session_id=sessionid)
        await bot.send(ev, f'[CQ:reply,id={mid}] \n' + ans)
        lmt.start_cd(group_id, 1)
        flmt.start_cd(group_id, 1)
    except Exception as e:
        traceback.print_exc()
        lmt.start_cd(group_id, 1)
        flmt.start_cd(group_id, 1)
        await bot.send(ev, f'claude发生错误：{e}')


@sv.on_fullmatch(('重置claude会话', '重置cld会话', '重置claude对话', '重置cld对话'))
async def reload_session(bot, ev: CQEvent):
    group_id = str(ev.group_id)
    user_id = str(ev.user_id)
    sessionid = get_sessionid(group_id, user_id)

    await bot.send(ev, "设置中...")

    pop_sessions(sessionid, None)

    if config_group[str(group_id)]["group_mode"]:
        if config_group[str(group_id)]["preset"]:
            message = await send_message_to_channel(message_text=charactor_prase(sessionid, 'init'), session_id=sessionid)
    else:
        if config_group[str(group_id)]["user"][str(user_id)]["preset"]:
            message = await send_message_to_channel(message_text=charactor_prase(sessionid, 'init'), session_id=sessionid)

    await bot.send(ev, f"会话已重置~")


@sv.on_fullmatch(('查看claude设置', '查看cld设置'))
async def check_config(bot, ev: CQEvent):
    group_id = str(ev.group_id)
    user_id = str(ev.user_id)
    sessionid = get_sessionid(group_id, user_id)

    msg = ''

    if config_group[str(group_id)]["group_mode"]:
        msg += '当前模式：群聊共享对话\n'
        msg += '当前人格：'
        preset = config_group[str(group_id)]["preset"]
        if not preset:
            msg += '默认claude'
        elif preset in persona_presets:
            msg += preset
        else:
            msg += '自定义人格'
    else:
        msg += '当前模式：个人独立对话\n'
        msg += '当前人格：'
        preset = config_group[str(group_id)]["user"][str(user_id)]["preset"]
        if not preset:
            msg += '默认claude'
        elif preset in persona_presets:
            msg += preset
        else:
            msg += '自定义人格'

    if config_group[str(group_id)]["safe_mode"]:
        msg += '\n安全模式：on\n'
    else:
        msg += '\n安全模式：off\n'


@sv.on_fullmatch(('重置claude人格', '重置cld人格'))
async def reload_preset(bot, ev: CQEvent):
    group_id = str(ev.group_id)
    user_id = str(ev.user_id)
    sessionid = get_sessionid(group_id, user_id)

    await bot.send(ev, "设置中...")
    pop_sessions(sessionid, None)

    if config_group[str(group_id)]["group_mode"]:
        update_config_group_json(str(group_id), 'preset', '')
        await bot.finish(ev, f'人格已重置! 当前人格：默认Claude！历史对话已清空！', at_sender=True)
    else:
        update_config_group_json(str(group_id), user_id, {'preset': ''}, True)
        await bot.finish(ev, f'人格已重置! 当前人格：默认Claude！历史对话已清空！', at_sender=True)


@sv.on_prefix(('切换claude人格', '切换cld人格'))
async def change_preset(bot, ev: CQEvent):
    group_id = str(ev.group_id)
    user_id = str(ev.user_id)
    sessionid = get_sessionid(group_id, user_id)

    new_persona = ev.message.extract_plain_text().strip()
    if new_persona not in persona_presets or (not new_persona):
        plist = []
        for pes in persona_presets:
            if persona_presets[pes]['safe'] or (not config_group[str(group_id)]["safe_mode"]):
                plist.append(pes)
        plist = '\n'.join(plist)
        await bot.finish(ev, '未找到此人格！目前可用人格：\n'+plist)

    if config_group[str(group_id)]["safe_mode"] and (not persona_presets[new_persona]['safe']) and not priv.check_priv(ev, priv.SU):
        await bot.finish(ev, '此人格仅维护组可设置！请联系维护组...')

    await bot.send(ev, "设置中...")
    pop_sessions(sessionid, None)

    if config_group[str(group_id)]["group_mode"]:
        update_config_group_json(str(group_id), 'preset', new_persona)
        message = await send_message_to_channel(message_text=charactor_prase(sessionid, 'init'), session_id=sessionid)
        await bot.finish(ev, f'本群claude人格已切换为{new_persona}！历史对话已清空！', at_sender=True)
    else:
        update_config_group_json(str(group_id), user_id, {
                                 'preset': new_persona}, True)
        message = await send_message_to_channel(message_text=charactor_prase(sessionid, 'init'), session_id=sessionid)
        await bot.finish(ev, f'个人claude人格已切换为{new_persona}！历史对话已清空！', at_sender=True)


@sv.on_prefix(('自定义claude人格', '自定义cld人格'))
async def custom_preset(bot, ev: CQEvent):
    group_id = str(ev.group_id)
    user_id = str(ev.user_id)
    sessionid = get_sessionid(group_id, user_id)

    if config_group[str(group_id)]["safe_mode"] and (not priv.check_priv(ev, priv.SU)):
        await bot.finish(ev, '自定义人格仅安全模式下可用！请联系维护组...')

    new_persona = ev.message.extract_plain_text().strip()
    if len(new_persona.split('|')) != 3:
        await bot.finish(ev, '自定义人格输入格式有误！格式为‘人格名|模板|前缀|后缀’')

    await bot.send(ev, "设置中...")
    pop_sessions(sessionid, None)

    if config_group[str(group_id)]["group_mode"]:
        update_config_group_json(str(group_id), 'preset', new_persona)
        message = await send_message_to_channel(message_text=charactor_prase(sessionid, 'init'), session_id=sessionid)
        await bot.finish(ev, f'本群claude人格已切换为{new_persona}！历史对话已清空！', at_sender=True)
    else:
        update_config_group_json(str(group_id), user_id, {
                                 'preset': new_persona}, True)
        message = await send_message_to_channel(message_text=charactor_prase(sessionid, 'init'), session_id=sessionid)
        await bot.finish(ev, f'个人claude人格已切换为{new_persona}！历史对话已清空！', at_sender=True)


@sv.on_prefix(('保存claude人格', '保存cld人格'))
async def save_preset(bot, ev: CQEvent):
    global persona_presets
    group_id = str(ev.group_id)
    user_id = str(ev.user_id)
    sessionid = get_sessionid(group_id, user_id)

    if not priv.check_priv(ev, priv.SU):
        await bot.finish(ev, '保存人格功能仅维护组可用...')

    new_persona = ev.message.extract_plain_text().strip()
    if len(new_persona.split('|')) != 5:
        await bot.finish(ev, '人格模板输入格式有误！格式为‘人格名|模板|前缀|后缀|安全码’')

    perlist = new_persona.split('|')

    if perlist[0].strip() in persona_presets:
        await bot.finish(ev, '此人格名已存在！’')

    await bot.send(ev, "设置中...")

    persona_presets[perlist[0].strip()] = {
        "desc": "",
        "init": perlist[1].strip(),
        "prefix": perlist[2].strip(),
        "suffix": perlist[3].strip(),
        "safe": int(perlist[4])
    }
    save_config(persona_presets, 'presets.json')
    await bot.finish(ev, f'人格{perlist[0].strip()}已保存！')


@sv.on_fullmatch(('切换claude对话模式', '切换cld对话模式'))
async def switch_group_mode(bot, ev: CQEvent):
    if not priv.check_priv(ev, priv.SUPERUSER):
        await bot.finish(ev, '此功能仅维护组可用~', at_sender=True)
        return
    group_id = str(ev.group_id)
    user_id = str(ev.user_id)

    sessionid = get_sessionid(group_id, user_id)

    pop_sessions(sessionid, None)

    if config_group[str(group_id)]["group_mode"]:
        update_config_group_json(str(group_id), 'preset', '')
        await bot.finish(ev, f'人格已重置! 当前人格：默认Claude！历史对话已清空！', at_sender=True)

    else:
        update_config_group_json(str(group_id), user_id, {'preset': ''}, True)
        await bot.finish(ev, f'人格已重置! 当前人格：默认Claude！历史对话已清空！', at_sender=True)


@sv.on_fullmatch(('切换claude安全模式', '切换cld安全模式'))
async def switch_safe_mode(bot, ev: CQEvent):
    if not priv.check_priv(ev, priv.SUPERUSER):
        await bot.finish(ev, '此功能仅维护组可用~', at_sender=True)
        return
    group_id = str(ev.group_id)
    user_id = str(ev.user_id)
    sessionid = get_sessionid(group_id, user_id)

    if config_group[str(group_id)]["safe_mode"] == 1:
        update_config_group_json(str(group_id), 'safe_mode', 0)
        await bot.finish(ev, f'安全模式已关闭，请注意身体……', at_sender=True)
    if config_group[str(group_id)]["safe_mode"] == 0:
        update_config_group_json(str(group_id), 'safe_mode', 0)
        await bot.finish(ev, f'安全模式已关闭，请注意身体……', at_sender=True)
