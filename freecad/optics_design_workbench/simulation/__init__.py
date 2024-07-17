from .processes import *
from .results_store import *


# make sure python and numpy random number generators both have 
# seeds that differ in all threads and processes
def makeGoodRandomSeed():
  import random
  import numpy.random
  import os
  import threading
  import time

  seed = int(str(threading.get_ident())+str(os.getpid())+str(int(1e7*time.time()))[-10:]) % (2**32)
  random.seed(seed)
  numpy.random.seed(seed)
makeGoodRandomSeed()
