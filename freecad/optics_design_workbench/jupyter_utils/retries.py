import functools
import traceback
import time

from .. import io

class retryOnError:
  def __init__(self, subject, maxRetries=3, callbackAfterRetries=0, callback=None):
    self.subject = subject
    self.maxRetries = maxRetries
    self.callbackAfterRetries = callbackAfterRetries
    self.callback = callback

  def __call__(self, func):
    @functools.wraps(func)
    def _wrapped(*args, _func=func, **kwargs):
      for retryNo in range(self.maxRetries+10):
        try:
          return _func(*args, **kwargs)
        except Exception:
          if retryNo >= self.maxRetries:
            raise
          elif retryNo >= self.callbackAfterRetries and self.callback:
            io.warn(f'exception raised while {self.subject}, running retry-callback and retrying... ({retryNo=}):\n\n'+traceback.format_exc())
            self.callback()
          else:
            io.warn(f'exception raised while {self.subject}, retrying... ({retryNo=}):\n\n'+traceback.format_exc())
          time.sleep(0.1)

    return _wrapped
