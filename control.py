import sys
from time import sleep
import time
from rpi_TM1638 import TMBoards

DIO = 17
CLK = 27
STB = [22]

TM = TMBoards(DIO, CLK, STB, 5)

# escreve na tela sem apgar (pro relogio)
def setMsg(msg):
    # TM.segments[0] = '        '
    TM.segments[0] = msg

# escreve na tela as msgs e mantem repetindo por 1 minuto
def setTxt(msg):
    if len(msg)>8:
        agora_min = time.localtime().tm_min
        while agora_min == time.localtime().tm_min:
            horse()
            for n in range(len(msg)-5):
                TM.segments[0] = '        '
                TM.segments[0] = msg[n:8+n]
                sleep(0.3)
            sleep(0.5)
    else:
        horse(1,20)
        TM.segments[0] = '        '
        TM.segments[0] = msg
        sleep(5)
    # horse()

def ledVerde(pos):
    TM.sendData((pos%8)*2+1,2,0)

def horse(times = 1,speed = 10, color = 'red'):
 TM.segments[0] = '        '
 TM.clearDisplay()
 while(times>0):
     a = 8
     while a > 0:
         if color == 'red':
             TM.leds[a-1]= True
         else:
             ledVerde(a-1)
         TM.segments[8-a,3] = True
         sleep(1.0/speed)
         TM.leds[a-1] = False
         TM.segments[8-a,3] = False
         a = a -1
     a = 7
     while a > 0:
         if color == 'red':
            TM.leds[8-a]= True
         else:
            ledVerde(8-a)
         TM.segments[a-1,3] = True
         sleep(1.0/speed)
         TM.leds[8-a] = False
         TM.segments[a-1,3] = False
         a = a -1
     times = times -1


def main():
    try:
        if sys.argv[1] == 'clear':
            TM.clearDisplay()
            print 'clear'
        elif sys.argv[1] == 'txt':
            print 'txt' + sys.argv[2]
            setTxt(sys.argv[2])
        elif sys.argv[1] == 'msg':
            print 'msg' + sys.argv[2]
            setMsg(sys.argv[2])
        else:
            horse()
    except Exception as e:
        print e + 'teste'

if __name__ == '__main__':
     main()
