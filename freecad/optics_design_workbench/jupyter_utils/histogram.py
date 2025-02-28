'''

'''

__license__ = 'LGPL-3.0-or-later'
__copyright__ = 'Copyright 2024  W. Braun (epiray GmbH)'
__authors__ = 'P. Bredol'
__url__ = 'https://github.com/zaphB/freecad.optics_design_workbench'


from numpy import *
from matplotlib.pyplot import *
import seaborn as sns
import pandas as pd

from .. import io


class Histogram:
  def __init__(self, X, Y, planeNormal, xInPlaneVec, radius=None,
               binCoords='cartesian', origin=None, **kwargs):
    self._planeNormal = planeNormal
    self._xInPlaneVec = xInPlaneVec
    if origin is None:
      origin = array([median(X), median(Y)])
    self._origin = origin

    # shift input data to origin
    X -= self._origin[0]
    Y -= self._origin[1]

    # get histogram
    if binCoords.lower() in 'cartesian':
      self._binCoords = 'cartesian'

      # overwrite bins if radius is given
      if radius is not None:
        bins = kwargs.pop('bins', 50)
        if hasattr(bins, '__len__') and len(bins) > 2:
          bins = len(bins)
        if not hasattr(bins, '__len__'):
          bins = [bins,bins]
        # set bins
        bins = list(bins)
        bins = [linspace(-radius, radius, bins[0]),
                linspace(-radius, radius, bins[1])]
        kwargs['bins'] = bins

      # calc histogram
      self.hist, self.binX, self.binY = histogram2d(X, Y, **kwargs)

      # calc bin areas
      self.binAreas = 1

    elif binCoords.lower() in 'polar':
      self._binCoords = 'polar'

      # overwrite bins if radius is given
      if radius is not None:
        bins = kwargs.pop('bins', 50)
        if hasattr(bins, '__len__') and len(bins) > 2:
          bins = len(bins)
        if not hasattr(bins, '__len__'):
          bins = [bins,bins]
        # set bins
        bins = list(bins)
        bins[1] = linspace(0, radius, bins[1])
        kwargs['bins'] = bins

      # calculate polar histogram
      self.hist, self.binX, self.binY = histogram2d(arctan2(X, Y), 
                                                    sqrt(X**2+Y**2), 
                                                    **kwargs)

      # calculate polar mode bin areas
      phi1, phi2, r1, r2 = self.binX[:-1], self.binX[1:], self.binY[:-1], self.binY[1:]
      (r1, phi1), (r2, phi2) = meshgrid(r1, phi1), meshgrid(r2, phi2)      
      self.binAreas = (phi2-phi1)*(r1+r2)/2*(r2-r1)

    else:
      raise ValueError(f'found invalid binCoord mode {repr(binCoors)}, '
                       f'expect one of "cartesian" or "polar"')

  def plot(self, cbar={}, title=None, scale='max', **kwargs):
    # setup default labels, axis parameters, etc depending on bin coords
    if self._binCoords == 'cartesian':
      projection = 'rectilinear'
      expectClass = 'Axes'
    elif self._binCoords == 'polar':
      projection = 'polar'
      expectClass = 'PolarAxes'
 
    # make sure projection of current axis is correct
    if gca().__class__.__name__.lower() != expectClass.lower():
      rows, cols, start, stop = gca().get_subplotspec().get_geometry()
      gcf().axes[start].remove()
      gcf().axes[start] = gcf().add_subplot(rows, cols, start+1, projection=projection)

    # warn if update not successful
    if gca().__class__.__name__.lower() != expectClass.lower():
      io.warn(f'tried to change axes class to {expectClass} but got {gca().__class__.__name__}')

    # scale histogram
    scaledHist = (self.hist/self.binAreas).T
    if scale == 'max':
      scaledHist = scaledHist / scaledHist.max()
    elif scale is not None:
      scaledHist = scaledHist / scale

    # increase phi-bin density in polar mode to make plot "nice and round"
    plotBinX, plotBinY, plotScaledHist = self.binX, self.binY, scaledHist
    if self._binCoords == 'polar':
      upscale = int(ceil(200/len(plotBinX)))
      if upscale > 1:
        plotBinX = concatenate([linspace(x1, x2, upscale+1)[:-1] for x1, x2 in zip(plotBinX[:-1], plotBinX[1:])]
                               +[[plotBinX[-1]]])
        plotScaledHist = concatenate(swapaxes([plotScaledHist.T]*upscale, 0, 1)).T

    # do actual plot
    gX, gY = meshgrid(plotBinX, plotBinY)
    pcolormesh(gX, gY, plotScaledHist, **kwargs)
    if type(cbar) is dict:
      colorbar(**cbar).set_label('hit density per bin')

    nx, ny, nz = self._planeNormal
    px, py, pz = self._xInPlaneVec
    ox, oy = self._origin
    if title is None:
      title = (f'plane normal = [{nx:.2f}, {ny:.2f}, {nz:.2f}],\n'
               f'projected $x$ = [{px:.2f}, {py:.2f}, {pz:.2f}]'
               +(f',\norigin = [{ox:.2e}, {oy:.2e}]' if not isclose(ox,0) or not isclose(oy,0) else ''))
    gca().set_title(title, fontsize=10)
    if self._binCoords == 'cartesian':
      gca().axis('equal')
      xlabel(r'projected $x$')
      ylabel(r'projected $y$')
    if self._binCoords == 'polar':
      if gca().get_title():
        gca().set_title(gca().get_title(), fontsize=10, y=1.09)
    gca().set_aspect('equal')
    tight_layout()

  def byAzimuth(self):
    '''
    Return histograms for each azimuthal angle bin. Only available in polar mode.
    '''
    if self._binCoords != 'polar':
      raise ValueError('byAzimuth is only available for polar histograms (created with binCoords="polar" argument)')

    scaledHist = (self.hist/self.binAreas).T
    res = []
    for phi1, phi2, histSlice in zip(self.binX[:-1], self.binX[1:], scaledHist.T):
      res.append(histSlice)
    return (self.binX[1:]+self.binX[:-1])/2, (self.binY[:-1]+self.binY[1:])/2, array(res)

  def plotByAzimuth(self):
    phi, r, H = self.byAzimuth()
    sns.lineplot(pd.DataFrame(H.T, index=r), errorbar=None).set(xlabel='radius $r$', ylabel='hit density per bin')
    legend(labels=[f'$\\phi={p/pi:.1f}\\pi$' for p in phi])
