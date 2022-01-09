import json

class bcolors:
    HEADER = '\033[95m'     #紫色
    OKBLUE = '\033[94m'     #蓝色
    OKCYAN = '\033[96m'     #亮蓝色
    OKGREEN = '\033[92m'    #绿色
    WARNING = '\033[93m'    #黄色
    FAIL = '\033[91m'       #红色
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

def printInput(input):
    print(bcolors.HEADER + ">>> " + bcolors.ENDC + input)

def printWarn(input):
    print(bcolors.WARNING + "[WARN] " + bcolors.ENDC + input)

def printSend(input):
    print(bcolors.OKBLUE + "[Send] " + bcolors.ENDC + input)

def printResend(input):
    print(bcolors.WARNING + "[Resend] " + bcolors.ENDC + input)

def printRecv(input, type = "ACK"):
    if type == "NAK":
        print(bcolors.FAIL + "[RECV] " + bcolors.ENDC + input)
    else:
        print(bcolors.OKGREEN + "[RECV] " + bcolors.ENDC + input)


