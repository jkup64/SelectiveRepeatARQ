import socket
import json
import time
import random
from binascii import crc32

Rn = 0
NakSent = False
AckNeeded = False
MAX_RECV = 1000
m = 4
Sw = 2**(m - 1)     # 滑动窗口大小
RAND_CHOICES = ["normal", "timeout"]
# slots哈希表，若收到则表示
slots = [False for i in range(MAX_RECV)]   

# 接收者使用服务端模型
IP_PORT = ("127.0.0.1", 1234)
BUF_SIZE = 1024

def sendACKorNAK(seq, type):
    send_frame = {
        "seq": seq,
        "type": type,
    }
    # frame["crc"] = crc32(json.dumps(send_frame).encode()) 写成”frame“也不报错？？？
    send_frame["crc"] = crc32(json.dumps(send_frame, indent=4).encode())
    json_of_send_frame = json.dumps(send_frame, indent=4)
    send_socket.sendall(json_of_send_frame.encode())
    print("[Send]", json_of_send_frame)
    return 

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as recv_socket:
    recv_socket.bind((IP_PORT))
    recv_socket.listen(2)
    send_socket, send_addr = recv_socket.accept()
    print(f"接收者: {IP_PORT} 接收到一个来自 {send_addr} 的连接")

    while True:
        recv_data = send_socket.recv(BUF_SIZE).decode()
        if not recv_data:
            break
        print("[Recv]", recv_data)
        frame = json.loads(recv_data)
        seq_of_frame = frame["seq"]

        # 检查帧是否损坏
        recv_crc = frame["crc"]
        del frame["crc"]
        crc_data = json.dumps(frame, indent=4).encode()
        calcul_crc = crc32(crc_data)

        print("[CRC]", recv_crc == calcul_crc)

        # 若帧损坏，且没发出过 NAK 则发送 NAK
        if (recv_crc != calcul_crc) and (not NakSent):
            sendACKorNAK(Rn, "NAK")
            NakSent = True
            continue

        # 若收到的帧不等于Rn，且对应位置没有被标记（之前还没收到）
        if (seq_of_frame != Rn) and (not NakSent):
            sendACKorNAK(Rn, "NAK")
            NakSent = True
            # 如果帧需要在窗口中，且对应位置未被标记
            if(Rn <= seq_of_frame < Rn + Sw) and (not slots[seq_of_frame]):
                slots[seq_of_frame] = frame
                while slots[Rn] != False:
                    Rn = Rn + 1
                AckNeeded = True

        # 教材伪代码居然没有seqNo等于Rn的情况
        if seq_of_frame == Rn:
            slots[seq_of_frame] = frame
            while slots[Rn] != False:
                Rn = Rn + 1
            AckNeeded = True
        
        # 只返回一个 ACK，ACK需要为Rn, 而非接受到的帧的序号
        if AckNeeded:
            sendACKorNAK(Rn, "ACK")
            AckNeeded = False
            NakSent = False

    send_socket.close()