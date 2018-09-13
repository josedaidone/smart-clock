# queijo

from time import sleep
import sys, time
from rpi_TM1638 import TMBoards
from daemon import Daemon

DIO = 17
CLK = 27
STB = [22]

TM = TMBoards(DIO, CLK, STB, 5)

class MyDaemon(Daemon):
        def run(self, msg):
            if msg:
                setTxt(msg)
            horse(1,20)
            antes = time.localtime()
            while(True):
                now = time.localtime()
                nowtxt = time.strftime("%H %M %S", now)
                if antes.tm_hour != now.tm_hour:
                    antes = now
                    if now.tm_hour == 19:
                        setTxt("sete horas - beijnho ba bunda")
                    elif now.tm_hour == 20:
                        setTxt("ja sao oito - hora de comer biscoito")
                else:
                    setMsg(nowtxt)
                sleep(1)

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
        horse()
        TM.segments[0] = '        '
        TM.segments[0] = msg
        sleep(5)

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

if __name__ == "__main__":
        daemon = MyDaemon('/tmp/clock_daemon.pid')
        if len(sys.argv) >= 2:
                if 'start' == sys.argv[1]:
                        daemon.start()
                elif 'stop' == sys.argv[1]:
                        daemon.stop()
                elif 'restart' == sys.argv[1]:
                        daemon.restart()
                elif 'msg' == sys.argv[1]:
                        daemon.stop()
                        daemon.start(sys.argv[2])
                else:
                        print "Unknown command"
                        sys.exit(2)
                sys.exit(0)
        else:
                print "usage: %s start|stop|restart" % sys.argv[0]
                sys.exit(2)
