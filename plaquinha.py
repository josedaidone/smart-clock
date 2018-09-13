from time import sleep
from rpi_TM1638 import TMBoards

DIO = 17
CLK = 27
STB = [22]

TM = TMBoards(DIO, CLK, STB, 2)

def setMsg(msg):
    if len(msg)>8:
        for i in range(2):
            for n in range(len(msg)-5):
                TM.segments[0] = '        '
                TM.segments[0] = msg[n:8+n]
                sleep(0.3)
            sleep(0.5)
    else:
        TM.segments[0] = '        '
        TM.segments[0] = msg


def ledVerde(pos):
    TM.sendData((pos%8)*2+1,2,0)

def horse(times = 1):
 TM.segments[0] = '        '
 TM.clearDisplay()
 while(times>0):
     a = 8
     while a > 0:
         TM.leds[a-1]= True
         # ledVerde(a-1)
         TM.segments[8-a,3] = True
         sleep(0.1)
         TM.leds[a-1] = False
         TM.segments[8-a,3] = False
         a = a -1
     a = 8
     while a > 0:
         # ledVerde(8-a)
         TM.leds[8-a]= True
         TM.segments[a-1,3] = True
         sleep(0.1)
         TM.leds[8-a] = False
         TM.segments[a-1,3] = False
         a = a -1
     times = times -1


def main():
         horse()
         setMsg('oi linda')
         sleep(1)
         horse()
         setMsg('        ')
         sleep(1)

if __name__ == '__main__':
     main()
