import sys
import socket
import json
import time
import random
from queue import Queue
from threading import Lock, Thread
from binascii import crc32
from types import FrameType
from colorPrint import *
from PySide2 import QtCore
from PySide2.QtWidgets import QApplication, QWidget, QTableWidgetItem
from PySide2.QtCore import Slot
from PySide2.QtUiTools import QUiLoader

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
RAND_CHOICES = ("normal", "corrupted")

# 发送者使用客户端模型
IP_SERVERPORT = ("127.0.0.1", 1234)
BUF_SIZE = 1024
send_lock = Lock()
io_lock = Lock()


class SenderWidget():
    def __init__(self):
        self.ui = QUiLoader().load("../ui/sender.ui")
        self.ui.button_commit1.clicked.connect(self.getAndStoreData)

        self.ui.cbox1.currentIndexChanged.connect(self.catFrame)

    @Slot()
    def getAndStoreData(self):
        """
        点击“发送”按钮时激发此函数，读取输入框的内容并加入到缓冲队列中。
        """
        to_send = self.ui.input_text.toPlainText()
        self.ui.input_text.clear()
        io_lock.acquire()
        printInput(to_send)
        io_lock.release()
        buffer_of_data.put(to_send)
    
    @Slot()
    def catFrame(self):
        frameSeq = int(self.ui.cbox1.currentText()[-1])
        self.ui.frame_cat.clear()
        try:
            json_frame = json.dumps(stored_frames[frameSeq], indent=4)
            self.ui.frame_cat.append(json_frame)
        except:
            self.ui.frame_cat.append(f"帧 {frameSeq} 还未产生")

    def resendFrame(self, i, send_socket):
        """
        重发帧：重新计算创建时间和校验值，更新窗口中储存的帧，并重发帧。
        """
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
        printResend(json_of_send_frame)
        io_lock.release()

    def recvFrameFromReceiver(self, send_socket):
        """
        接受线程的功能：对接收者返回的帧进行校验，然后对完整帧的类型进行判断：
        若为NAK则立即重发，
        若为ACK则移动滑动窗口，将从窗口中删除数据帧，并停止计时；
        """
        global Sf
        while True:
            recv_data = send_socket.recv(BUF_SIZE).decode()
            frame = json.loads(recv_data)
            frame_type = frame["type"]
            io_lock.acquire()
            printRecv(recv_data, type=frame_type)
            io_lock.release()

            # 检查接受者发回来的帧是否损坏
            recv_crc = frame["crc"]
            del frame["crc"]
            crc_data = json.dumps(frame, indent=4).encode()
            calcul_crc = crc32(crc_data)
            # 若帧损坏则睡眠？-> 进入下一轮接受的阻塞状态
            if recv_crc != calcul_crc:
                io_lock.acquire()
                printWarn("接受帧CRC校验异常")
                io_lock.locked()
                continue

            # 若为NAK
            if frame_type == "NAK":
                nakNo = frame["seq"]
                if Sf <= nakNo < Sn:
                    # 重发会重新计算 创建时间 和 crc, 相当于重新计时
                    if nakNo < Sw:
                        self.ui.table1.setItem(nakNo, 3, QTableWidgetItem("NAK"))
                    else:
                        self.ui.table1.setItem(Sw - (Sn - nakNo), 3, QTableWidgetItem("NAK"))
                    time.sleep(0.8) # 方便人观察到显示过”NAK“
                    self.resendFrame(nakNo, send_socket)
            
            elif frame_type == "ACK":
                ackNo = frame["seq"] 
                if Sf <= ackNo <= Sn:
                    while Sf < ackNo:
                    # 注意：需要在此函数内将Sf声明为全局变量，否则将会被解释成局部变量
                    # 在函数类修改变量将会被视为局部变量（python特性）
                        stored_frames[Sf]["is_accepted"] = True
                        if Sf < Sw:
                            self.ui.table1.setItem(Sf, 3, QTableWidgetItem("ACK"))
                        else:
                            self.ui.table1.setItem(Sw -(Sn - Sf), 3, QTableWidgetItem("ACK"))
                        Sf = Sf + 1
                        self.ui.label_Sf.setText(f"Sf = {Sf%Sw}")

    def checkTimeoutAndResend(self, send_socket):
        '''
        检查超时线程的功能：自旋，检查滑动窗口内是否有帧已经超时，若有则重发。
        '''
        while True:
            time.sleep(1)
            # 扫描窗口中的所有帧是否已经超时
            for i in range(Sf, Sn):
                # 接受到的帧停止计时
                if stored_frames[i]["is_accepted"] == False:
                    # 对超时帧进行重发
                    if (time.time() - stored_frames[i]["create_time"]) > timeout_limit:
                        printWarn("超时重发:{}".format(stored_frames[i]))
                        self.resendFrame(i, send_socket)

    def connect(self, ip_port = IP_SERVERPORT):
        '''
        程序执行包括 4 个线程，主线程实现图形界面，主线的子线程——连接线程用于接受上层输入并成帧发送
        连接线程的 2个子线程分别负责 接受来自接受者发送的NAK或ACK信号 和 检查超时并重发
        由于socket建立在传输层之上，具有收发双队列，故收发不会产生冲突，但主线程中的发 和 子线程中的重发 可能会产生冲突，需要加锁
        连接线程的功能：自旋，当缓冲队列不为空时取出数据，成帧、定时、存帧、发送帧
        '''
        global Sn, Sf
        try:
            send_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            send_socket.connect(ip_port)
            thread_of_recv = Thread(target=self.recvFrameFromReceiver, args=(send_socket,), daemon=True)
            thread_of_checkTimeout = Thread(target=self.checkTimeoutAndResend, args=(send_socket,), daemon=True)
            thread_of_recv.start()
            thread_of_checkTimeout.start()
            while True:
                # 窗口满则睡眠
                if (Sn - Sf) >= Sw:
                    time.sleep(1)
                    continue
                
                # GetData
                if  not buffer_of_data.empty():
                    to_send = buffer_of_data.get()
                    if to_send == "exit()":
                        break
                else:
                    time.sleep(1)
                    continue

                # MakeFrame
                frame = {
                    "seq": Sn,
                    "data": to_send,
                    "create_time": time.time(),
                    "is_accepted": False
                }
                # 没有抽中“corrupted”才能crc校验通过
                rand_res = random.choice(RAND_CHOICES)
                if rand_res == "corrupted":
                    io_lock.acquire()
                    printWarn("抽中损坏——crc计算异常")
                    io_lock.release()
                    frame["crc"] = crc32(json.dumps(frame, indent=4).encode()) + 1
                else:
                    frame["crc"] = crc32(json.dumps(frame, indent=4).encode())
                json_of_send_frame = json.dumps(frame, indent=4)

                # Store Frame
                stored_frames.append(frame)

                # Send Frame
                send_lock.acquire()
                send_socket.sendall(json_of_send_frame.encode())
                send_lock.release()

                io_lock.acquire()
                printSend(json_of_send_frame)
                io_lock.release()

                self.ui.cbox1.addItem(f"帧{Sn}")
                if Sn < Sw:
                    self.ui.table1.insertRow(Sn)
                    self.ui.table1.setItem(Sn, 0, QTableWidgetItem(str(Sn%Sw)))
                    self.ui.table1.setItem(Sn, 1, QTableWidgetItem(to_send))
                    self.ui.table1.setItem(Sn, 2, QTableWidgetItem("True"))
                else:
                    self.ui.table1.insertRow(Sw)
                    self.ui.table1.setItem(Sw, 0, QTableWidgetItem(str(Sn % Sw)))
                    self.ui.table1.setItem(Sw, 1, QTableWidgetItem(to_send))
                    self.ui.table1.setItem(Sw, 2, QTableWidgetItem("True"))                    
                    self.ui.table1.removeRow(0)
                
                # Sn = Sn + 1
                Sn = Sn + 1
                self.ui.label_Sn.setText(f"Sn ={Sn%Sw}")

        finally:
            send_socket.close()
            
if __name__ == "__main__":
    QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_ShareOpenGLContexts)
    app = QApplication(sys.argv)
    sw = SenderWidget()
    sw.ui.show()
    thread_of_conn = Thread(target=sw.connect, args=(IP_SERVERPORT,), daemon=True)
    thread_of_conn.start()
    sys.exit(app.exec_())