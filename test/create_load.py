import os
import math
import time
import datetime

#t1 = time.time()
#print(t1)
#time.sleep(2)
#t2 = time.time()
#print(t2)
#d = t2 - t1
#
#print("{} [{}]".format(d, type(d)))

#t1 = datetime.datetime.now()
#time.sleep(1)
#t2 = datetime.datetime.now()
#d = t2 - t1
#print(d)
#print(int(d))

#xyz = datetime.timedelta(seconds=int(uptime))


def do_work(t):
    start_time = time.time()
    for i in range(1000000000):
        for j in range(10000):
            x = math.sqrt(i * i + j * j)
            if time.time() - start_time > t:
                return
si = input("Start interval of threads (default=1) ")
if not si:
    si = 1
else:
    si = int(si)

dt = input("How many seconds per thread (default=5) ")
if not dt:
    dt = 5
else:
    dt = int(dt)

tc = input("How many threads (default=1) ")
if not tc:
    tc = 1
else:
    tc = int(tc)

def start_work():
    print("Starting, I am {}".format(os.getpid()))
    for index, t in enumerate(range(tc)):
        new_pid = os.fork()
        if new_pid == 0:
            print("Starting child {}".format(index + 1))
            do_work(dt)
            print("Taking a nap {}".format(index + 1))
            time.sleep(4)
            print("End of nap  {}".format(index + 1))
            do_work(dt)
            print("Ended child {}".format(index + 1))
            return
        time.sleep(si)
#    else:
#        print("I'm the parent: {}".format(os.getpid()))
    print("Done starting child processes)")
start_work()
