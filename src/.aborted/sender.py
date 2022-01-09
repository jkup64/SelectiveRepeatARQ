import socket
import json
import time
import random
from queue import Queue
from threading import Lock, Thread
from binascii import crc32

m = 4
Sw = 2**(m-1)
# Sf和Sn暂时使用绝对标号
Sf = 0                   # 待确认的下一个元素
Sn = 0                   # 待发送的下一个元素
timeout_limit = 3        # 超时时间阈值设置为5秒
# counter_of_frame = 0     # 产生的第几个帧
buffer_of_data = Queue() # 储存上层数据的缓冲区
stored_frames = []       # 储存历史所有帧

# 掷塞子：环节抽到对应异常就会出错
# corrupted 对应crc错误
# timeout 对应不发送，导致超时
RAND_CHOICES = ("normal", "corrupted", "timeout")

# 发送者使用客户端模型
IP_SERVERPORT = ("127.0.0.1", 1234)
BUF_SIZE = 1024
send_lock = Lock()
io_lock = Lock()

def getAndStoreData():
    while True:
        # 睡眠短暂时间，防止独占锁
        time.sleep(0.2)
        # 对于用户输入的数据先放入缓冲区，成帧后从缓冲区删除
        io_lock.acquire()
        to_send = input("\n>>> ").strip()
        io_lock.release()
        buffer_of_data.put(to_send)

def resendFrame(i, send_socket):
    # 重新计算 创建时间 和 crc校验
    frame = stored_frames[i]
    frame["create_time"] = time.time()
    del frame["crc"]
    crc_data = json.dumps(frame, indent=4).encode()
    frame["crc"] = crc32(crc_data)
    
    # 更新本地储存帧，并重发帧
    stored_frames[i] = frame
    json_of_send_frame = json.dumps(frame, indent=4)
    send_lock.acquire()
    send_socket.sendall(json_of_send_frame.encode())
    send_lock.release()
    io_lock.acquire()
    print("[Resend]",json_of_send_frame)
    io_lock.release()

def recvFrameFromReceiver(send_socket):
    global Sf
    while True:
        recv_data = send_socket.recv(BUF_SIZE).decode()

        io_lock.acquire()
        print("[Recv]", recv_data)
        io_lock.release()

        frame = json.loads(recv_data)
        # 检查接受者发回来的帧是否损坏
        recv_crc = frame["crc"]
        del frame["crc"]
        crc_data = json.dumps(frame, indent=4).encode()
        calcul_crc = crc32(crc_data)
        # 若帧损坏则睡眠？-> 进入下一轮接受的阻塞状态
        if recv_crc != calcul_crc:
            print("[ERROR] 接受帧CRC校验异常")
            continue

        frame_type = frame["type"]
        # 若为NAK
        if frame_type == "NAK":
            nakNo = frame["seq"]
            if Sf <= nakNo < Sn:
                # 重发会重新计算 创建时间 和 crc, 相当于重新计时
                resendFrame(nakNo, send_socket)
        
        elif frame_type == "ACK":
            ackNo = frame["seq"] - 1
            if Sf <= ackNo < Sn:
                frame["is_accepted"] = True
                # 注意：需要在此函数内将Sf声明为全局变量，否则将会被解释成局部变量
                # 在函数类修改变量将会被视为局部变量（python特性）
                Sf = Sf + 1

def checkTimeoutAndResend(send_socket):
    while True:
        # print("stored_frames", stored_frames)
        time.sleep(1)
        # 扫描窗口中的所有帧是否已经超时
        for i in range(Sf, Sn):
            # 接受到的帧停止计时
            if stored_frames[i]["is_accepted"] == False:
                # 对超时帧进行重发
                if (time.time() - stored_frames[i]["create_time"]) > timeout_limit:
                    resendFrame(i, send_socket)
                    print("[超时重发]", stored_frames[i])

# Main
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as send_socket:
    send_socket.connect(IP_SERVERPORT)
    # 程序执行包括 4 个线程，主线程实现图形界面，主线的子线程——连接线程用于接受上层输入并成帧发送
    # 连接线程的 2个子线程分别负责 接受并缓存上层数据、接受来自接受者发送的NAK或ACK信号 和 检查超时并重发
    # 由于socket建立在传输层之上，具有收发双队列，故收发不会产生冲突，但主线程中的发 和 子线程中的重发 可能会产生冲突，需要加锁
    thread_of_recv = Thread(target=recvFrameFromReceiver, args=(send_socket,), daemon=True)
    thread_of_checkTimeout = Thread(target=checkTimeoutAndResend, args=(send_socket,), daemon=True)

    thread_of_recv.start()
    thread_of_checkTimeout.start()
    while True:
        # 窗口满则睡眠
        if (Sn - Sf) >= Sw:
            time.sleep(1)
            continue
        
        # GetData
        if buffer_of_data.empty():
            to_send = buffer_of_data.get()
            if to_send == "exit()":
                break

        # MakeFrame
        frame = {
            "seq": Sn,
            "data": to_send,
            "create_time": time.time(),
            "is_accepted": False
        }
        # 没有抽中“corrupted”才能crc校验通过
        rand_res = random.choice(RAND_CHOICES)
        frame["crc"] = crc32(json.dumps(frame, indent=4).encode())
        json_of_send_frame = json.dumps(frame, indent=4)

        # Store Frame
        stored_frames.append(frame)

        send_lock.acquire()
        send_socket.sendall(json_of_send_frame.encode())
        send_lock.release()

        io_lock.acquire()
        print("[Send]",json_of_send_frame)
        io_lock.release()

        # Sn = Sn + 1
        Sn = Sn + 1

