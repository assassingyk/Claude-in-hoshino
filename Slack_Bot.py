import json
import os
import time
import uuid
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from slack_sdk.errors import SlackClientError

sessions = {}
queue_message = {}

working_path = os.path.abspath(os.path.realpath(os.path.dirname(__file__)))


# 在[Slack App]->[OAuth & Permissions]->[User OAuth Token] (xoxp-...)中找到令牌
SLACK_USER_TOKEN = ""

# channel_id在频道URL中找到，例如https://app.slack.com/client/T000000000/C0533PLC7V4 中的C0533PLC7V4
# 只需要打开你想要发送消息的频道，然后在地址栏中找到
# 必须填写正确的channel_id，否则无法使用
channel_id = ""

# claude_id可以在 View App Details（查看应用详情） 中的 Member ID （成员 ID） 中找到
# 本ID是Slack内部使用的ID，不是Slack用户名或bot ID，不要混淆
# 本ID是用来标识Claude回复的消息的，如果不使用本ID，不太容易区分Claude的回复和我们用来发送消息的Bot的回复
# 并且，如果假设在消息列中有实时在线的用户的回复，有ID就可以辨认出来
# 因此也建议用一个专用的Slack工作区，不要和其他用户使用的混在一起
claude_id = ""

# 观察中发现如果在Claude回复后还处在Typing状态， 那么这时候发送消息， Claude的反应会受影响
# 角色扮演的影响非常大， 所以默认开启
# 如果不需要角色扮演等上下文相关或不需要精确的回复，可以关闭
# !注意！经过测试Claude同时Typing的回复数量有限，如果超过一定数量，Claude会暂缓其他Typing并等待正在进行的回复完成后再继续
wait_til_message_finish = True


# 使用机器人TOKEN实例化Web客户端
client = WebClient(token=SLACK_USER_TOKEN)
# 会话列表用于记录会话ID和消息Time Stamp(ts) ID，用于辨认响应消息，
# 会话锁以及防止重复发送消息导致消息错乱, 只要Claude开始回复(指Typing)，就会解锁会话，实际时间应该在不到1秒左右
# 短的等待时间换来消息列表对齐是值得的

def load_auth():
    global SLACK_USER_TOKEN, channel_id, claude_id, client
    with open(os.path.join(working_path, 'config.json'),"r", encoding='utf8') as config_file:
        configs = json.load(config_file)
    SLACK_USER_TOKEN = configs["slack"]["User_OAuth_Token"]
    channel_id = configs["slack"]["channel_id"]
    claude_id = configs["slack"]["claude_id"]
    client = WebClient(token=SLACK_USER_TOKEN)

def load_sessions():
    global sessions
    with open(os.path.join(working_path, 'sessions.json'),"r", encoding='utf8') as config_file:
        sessions = json.load(config_file)

def save_sessions():
    global sessions
    with open(os.path.join(working_path, 'sessions.json'),"w", encoding='utf8') as config_file:
        json.dump(sessions, config_file, ensure_ascii=False, indent=4)

def pop_sessions(key, value=None):
    global sessions
    dis=sessions.pop(key, value)
    save_sessions()
    return dis


# 最大重试次数，如果响应时间超过3秒，则更新消息重试，重试次数超过最大次数，则返回未响应
max_retries = 5

def midware(message_text,session_id):
    global channel_id
    return send_message_to_channel(channel_id, message_text,session_id)

def send_message_to_channel(channel_id:str=channel_id, message_text:str = "",session_id:str = "g01"):
    try:
        if SLACK_USER_TOKEN[:4] != "xoxp":
            return "USER_TOKEN错误，请检查是否填写正确。"
        is_new_session = False
        uniq_ID = message_text + str(uuid.uuid1())[:8]

        if not queue_message.get(session_id):
                queue_message[session_id] = [uniq_ID]
        else:
            queue_message.get(session_id).append(uniq_ID)

        # 如果会话ID在会话列表中，则等待会话解锁
        while queue_message.get(session_id) and uniq_ID in queue_message.get(session_id) and queue_message.get(session_id).index(uniq_ID) > 0:
            print(f"等待会话解锁... {session_id} 1 秒后重试...")
            time.sleep(1)
        if not queue_message.get(session_id) or uniq_ID not  in queue_message.get(session_id):
            return
        # 如果会话ID不在会话列表中，则发送新消息，并记录会话ID和time stamp, 否则发送消息列回复
        if session_id not in sessions:
            is_new_session = True
            result = send_message(channel_id,message_text)
            if not result['ok']:
                # 解锁会话
                pop_message(session_id,uniq_ID)
                return result['error']
            sessions[session_id] = result['ts']
            save_sessions()
        else:
            result = send_message(channel_id,message_text,sessions.get(session_id))
        if not result['ok']:
            # 解锁会话
            pop_message(session_id,uniq_ID)
            return result['error']
        # 记录time stamp用于后续辨认响应消息
        ts = result['ts']
        # 初始化响应为_Typing…_，表示正在等待响应
        response = '_Typing…_'
        poped_item = None
        # 记录响应开始时间,重试次数
        start_time = time.time()
        reties = 1
        # 如果响应以_Typing…_结尾，则继续等待响应
        while response.strip().endswith('_Typing…_'):
            replies = receive_message(channel_id=channel_id,ts=sessions.get(session_id),oldest=ts)
            # 如果replies['ok']为False或消息列表长度小于等于1，则表示没有响应
            if not replies:
                # 解锁会话
                pop_message(session_id,uniq_ID)
                raise SlackApiError("未收到Claude响应，请重试。")
            if not replies['ok'] or (time.time() - start_time > 10 and len(replies['messages']) <= 1):
                if replies['error'] == 'ratelimited':
                    print(f"被限速了， 将在5秒后重试...")
                    time.sleep(5)
                    continue
                # 如果重试次数超过{max_retries}次，则返回未响应
                # 否则更新消息从而触发@Claude的响应
                if reties >= max_retries:
                    # 解锁会话
                    pop_message(session_id,uniq_ID)
                    return f'以重试{max_retries}次，未收到Claude响应，请重试。'
                else:
                    # 如果重试次数未超过{max_retries}次，则更新消息从而触发@Claude的响应
                    print(f"重试 {reties} 次... 最大重试次数: {max_retries} 次")
                    update_message(channel_id, ts, message_text)
                    start_time = time.time()
                    reties += 1
                    continue
            if len(replies['messages']) <= 1:
                continue
            for index,message in enumerate(replies['messages'][1:],start=1):
                if message['user'] != claude_id:
                    continue
                response = message['text']
                if index < len(replies['messages']) - 1 and any(warn_tip in replies['messages'][index + 1]['text'] for warn_tip in["*Please note:*", "Oops! Claude was un"]):
                    client.chat_delete(
                        channel=channel_id,
                        ts=replies['messages'][-1]['ts'],
                        as_user=True
                        )
                pop_message(session_id,uniq_ID, not is_new_session and not wait_til_message_finish)
                # if queue_message.get(session_id) and uniq_ID in queue_message.get(session_id) and not is_new_session and not wait_til_message_finish:
                #     pop_index = queue_message.get(session_id).index(uniq_ID)
                #     queue_message.get(session_id).pop(pop_index)
                break
            time.sleep(1)
            
        # print(f"Message sent to channel {channel_id}...\nResponds:\n{response}")
        # 解锁会话
        pop_message(session_id,uniq_ID,is_new_session or wait_til_message_finish)
        # if queue_message.get(session_id) and uniq_ID in queue_message.get(session_id) and (is_new_session or wait_til_message_finish):
        #     pop_index = queue_message.get(session_id).index(uniq_ID)
        #     queue_message.get(session_id).pop(0)
        return response
    except SlackApiError as e:
        print(f"Error posting message to channel {channel_id}: {e}")
        # 解锁会话
        pop_message(session_id,uniq_ID)
        return str(e.response['error'])
    # except nonetype error
    except SlackClientError as e:
        print(f"Error posting message to channel {channel_id}: {e}")
        # 解锁会话
        pop_message(session_id,uniq_ID)
        return str(e)
    except TypeError as e:
        print(f"Error posting message to channel {channel_id}: {e}")
        # 解锁会话
        pop_message(session_id,uniq_ID)
        return str(e)
    except Exception as e:
        print(f"Error posting message to channel {channel_id}: {e}")
        # 解锁会话
        pop_message(session_id,uniq_ID)
        return str(e)


### 普通方法区 ###

def pop_message(session_id:str="",uniq_ID:str="",bool_expression:bool=True):
    if queue_message.get(session_id) and uniq_ID in queue_message.get(session_id) and bool_expression:
        pop_index = queue_message.get(session_id).index(uniq_ID)
        queue_message.get(session_id).pop(pop_index)

def switch_message_mode():
    global wait_til_message_finish
    queue_message.clear()
    wait_til_message_finish = not wait_til_message_finish
    return wait_til_message_finish

def get_message_mode():
    return wait_til_message_finish


### Slack API 方法区 ###

# 发送@Claude的消息
# 如果thread_ts为空，则发送新消息
# 如果thread_ts不为空，则发送消息列回复
def send_message(channel_id,text:str,tread_ts:str = ''):
    try:
        # 使用Web客户端调用chat.postMessage方法
        result = client.chat_postMessage(
            channel=channel_id, 
            text=f'<@{claude_id}>{text}',
            thread_ts = tread_ts
        )
        return result
    except SlackApiError as e:
        print(f"Error posting message to channel {channel_id}: {e}")


# 获取消息列
def receive_message(channel_id,ts,oldest):
    try:
        # 使用Web客户端调用conversations.replies方法
        result = client.conversations_replies(  ts = ts, 
                                                channel = channel_id,
                                                oldest = oldest)
        return result
    except SlackApiError as e:
        print(f"Error posting message to channel {channel_id}: {e}")


# 更新消息, 用于触发@Claude的响应
def update_message(channel_id,ts,text:str):
    try:
        # 使用Web客户端调用chat.update方法
        result = client.chat_update(
            channel=channel_id, 
            ts=ts,
            text=f'<@{claude_id}>{text}'
        )
        return result
    except SlackApiError as e:
        print(f"Error posting message to channel {channel_id}: {e}")



# for test use only
if __name__ == "__main__":
    os.system('cls')
    session_id=str(uuid.uuid1())[:8]
    print(f"当前会话 ID : {session_id} <quit[退出]> <clear[重置会话]>")
    while True:
        # make input text green
        text = input(f"\033[32m你\033[0m:\n    ")
        if not text:
            print("Invalid input!")
            continue
        if text.lower() == "quit":
            exit()
        elif text.lower() == "clear":
            print("\033[33m" + "Clearing the screen..." + "\033[0m")
            os.system('cls')
            session_id = str(uuid.uuid1())[:8]
            print(f"当前会话 ID : {session_id} <quit[退出]> <clear[重置会话]>")
            continue
        
        
        print(f"\033[33mClaude\033[0m:")
        response = send_message_to_channel(message_text=text,session_id=session_id)
        print(f"   \033[33m{response}\033[0m")
