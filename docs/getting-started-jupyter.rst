
Jupyter integration
====================

To install the workbench as a regular python package run ``pip install optics_design_workbench``. Note that within the FreeCAD python shell the workbench is available as a namespace package *freecad.optics_design_workbench*. However in external python interpreters the package is called *optics_design_workbench*, i.e., not being part of the *freecad* namespace. The *freecad* namespace package can only be imported in the FreeCAD-internal python shell (at the time of writing).

Therefore within FreeCAD's python shell use ``import freecad.optics_design_workbench``. In other python interpreters use ``import optics_design_workbench``.


Visualize power density histograms
----------------------------------

.. _`previous chapter`: getting-started-freecad

.. _`github repository`: https://github.com/zaphB/freecad.optics_design_workbench/tree/master/examples/1-getting-started

As a very first example let's visualize the data generated at the end of the `previous chapter`_, in which we constructed a simple optical assembly and ran a Monte-Carlo simulation with 100k rays. The .FCStd file and notebooks discussed in the following are available in the `github repository`_.

Our analysis notebook begins with importing matplotlib and workbench modules:

.. notebook:: ../examples/1-getting-started/visualize-power-density
  :cells: 0

We proceed by opening the most recent raw/ subfolder of the simulation project:

.. notebook:: ../examples/1-getting-started/visualize-power-density
  :cells: 1,2

The message printed by the *loadHits* method shows the glob pattern used to load the data files.
Let's go on by calculating and plotting a 2D histogram to obtain the power density incident on the detector defined in our .FCStd file:

.. notebook:: ../examples/1-getting-started/visualize-power-density
  :cells: 3-4

We find all ray hits concentrated in the center of our detector, which is expected as we placed our detector close to the focal point of our beam. To arrive at this histogram a projection of the 3D ray-hit point cloud to a 2D coordinate system is necessary. The *hits.histogram* method will try to automatically do this behind the scenes, but this may fail e.g. for complex shaped curved detector geometries. The plot title displays the auto detected detector-plane normal vector, the 3D vector that corresponds to the *x* direction in the plot and the detected origin point in 3D that corresponds to the 2D *x=0*, *y=0*.

To better resolve the shape of our spot we adjust the histogram limits by passing a custom bin-edge list *bins=linspace(...)* and we employ logarithmic scaling of the density:

.. notebook:: ../examples/1-getting-started/visualize-power-density
  :cells: 5-6

The plot is generated using matplotlib, therefore we can use any other matplotlib calls to e.g. customize plot limits or save the plot the plot to disk. Now we can clearly resolve true shape of our spot on the detector.

.. _`earlier FWHM example`:
.. notebook:: ../examples/1-getting-started/visualize-power-density
  :cells: 7-8

The entire jupyter notebook file is available for download here__. A more detailed documentation of all the available options is found in the API reference:

.. __: https://github.com/zaphB/freecad.optics_design_workbench/tree/master/examples/1-getting-started/visualize-power-density.ipynb

.. currentmodule:: optics_design_workbench.jupyter_utils
.. autosummary:: 
  :toctree: api

  rawFolders
  rawFolderByIndex
  latestRawFolder
  RawFolder
  Hits
  Histogram


Accessing an .FCStd file from jupyter
-------------------------------------

In next sections we will take a look at how the ``jupyter_utils`` submodule can be used to modify to the .FCStd file and to start simulations from a jupyter notebook. This allows to optimize geometric parameters, e.g. the lens radius, guided by metrics derived from a Monte-Carlo simulation, e.g. the spot FHWM.

.. warning::
  When opening an *.FCStd* file from a jupyter notebook using the *FreecadDocument* class **do not** open the same *.FCStd* document in an independent FreeCAD GUI, because bad things will happen when both jupyter and the FreeCAD GUI want to save changes to disk. 

  A save way to open the FreeCAD GUI is introduced later in this example in section `Modifying properties and running simulations`_.

We open .FCStd files using the *FreecadDocument* class:

.. _`notebook cell above`:
.. notebook:: ../examples/1-getting-started/optimize-spotsize
  :cells: 3

The above cell shows how to use a *FreecadDocument* as a context manager and print the file path and the *Radius* property of the *Sphere* object that we created to construct the spherical lens in our project.

Without any arguments, the *FreecadDocument* constructor will try to detect which .FCStd file you may want to open. This works if your notebooks are in the same folder with a single .FCStd file, or if your notebooks are in the *.OpticsDesign* folder (or sub folders therein). To ensure the right *.FCStd* file is addressed you can pass a path to the constructor.

The way we are accessing objects and properties in the *.FCStd* using the *FreecadDocument* class tries to mimic the behavior of FreeCAD's internal python shell. Within FreeCAD you would access and manipulate the *Sphere*'s *Radius* property like this:

>>> doc = App.ActiveDocument
>>> doc.Sphere.Radius
10.0 mm
>>> doc.Sphere.Radius = 10.1
>>> doc.Sphere.Radius
10.1 mm

Comparing this with the `notebook cell above`_ you may notice an important difference: ``doc.Sphere.Radius`` will immediately give us a number in FreeCAD's internal shell, but will give us a ``<FreecadProperty ...>`` object when using the *FreecadDocument* class in an external jupyter notebook. To get the numerical value of the property we have to call geht *.get()* method of the *FreecadProperty* object.

Therefore, when using the *FreecadDocument* class from a jupyter notebook, always make sure to call the *.get()* method on a *FreecadProperty* objects to retrieve numerical (or string) values.


Modifying properties and running simulations
--------------------------------------------

Whereas for retrieving values the additional *.get()* call is necessary, updating properties using the *FreecadDocument* class is fully analogous to how you would do it from within FreeCAD.

.. notebook:: ../examples/1-getting-started/optimize-spotsize
  :cells: 4

Typically, when modifying the *.FCStd* file from in the jupyter notebook it is desirable to take a look at the 3D model in the FreeCAD GUI from time to time. **Do not** open the .FCStd file in an independent FreeCAD GUI. This independent GUI will not notice any changes you apply with your jupyter notebook and you will most likely break your simulations in awful ways. Instead, launch the FreeCAD GUI from your jupyter notebook like this:

.. notebook:: ../examples/1-getting-started/optimize-spotsize
  :cells: 5

This call is blocking in the jupyter notebook until the FreeCAD GUI is closed again again and thereby ensures that the file on disk is only written by one party at a time [#]_. The last missing piece to run a parameter optimization is the ability to run a simulation from jupyter. The following cell shows how to do it:

.. notebook:: ../examples/1-getting-started/optimize-spotsize
  :cells: 6

To avoid having to wait for the 100k rays the we used to simulate at the beginning of this chapter, we update the *EndAfterRays* property of the *OpticalSimulationSettings* object in our project to 1k rays before starting.

As the final print statement in the cell above shows *doc.runSimulation(...)* directly returns the *RawFolder* object created during the simulation, so we can immediately calculate and plot the histogram from the point cloud data with a single line.

For detailed list of all available arguments and methods see the API reference of the classes giving access to *.FCStd* files from jupyter notebooks:

.. currentmodule:: optics_design_workbench.jupyter_utils
.. autosummary:: 
  :toctree: api

  FreecadDocument
  FreecadObject
  FreecadProperty



Running a simple parameter sweep
--------------------------------

Let's now combine what we built so far and calculate the spot's full width half maximum (FWHM) for a range of different lens radii. We turn the `earlier FWHM example`_ into a function that calculates a single FWHM value from a given point cloud *hits*. 

.. notebook:: ../examples/1-getting-started/optimize-spotsize
  :cells: 8

The function contains a few tweaks to make it more robust with respect to less well-focussed spots. Whenever you are defining a metric that you would like to study as a function of geometric parameters it is very important to make it robustly handle all the parameter space you want to explore.

Then we loop over the radius values that we would like to check, run a simulation for each, and calculate the FWHM from the resulting *rawRolder* result, store all the *fwhms* in a list, and finally plot the FWHM results vs. the lens radius.

.. notebook:: ../examples/1-getting-started/optimize-spotsize
  :cells: 9-10

The plot clearly shows at which lens radius we observe the smallest spot. To store the optimization result permanently in the .FCStd file we run one final cell that sets the radius to the radius value with smallest FWHM:

.. notebook:: ../examples/1-getting-started/optimize-spotsize
  :cells: 11

Congratulations, you just finished your first parameter optimization! 

The direct access through the *FreecadDocument* class that we used for our parameter sweep is mighty as it gives access to any object in the document tree. But it becomes a little clumsy when you think about optimizing many parameters in parallel. The expressions like *doc.Sphere.Radius*, *doc.Sphere.Placement.Base.x* are based on the .FCStd document-tree structure and are not always as descriptive as you would wish to keep the scripts human readable. The next section will introduce a more convenient way for parameter sweeping, which is suitable for problems with many free parameters and allows to easily apply algorithms from `scipy.optimize` for optimization.

The entire jupyter notebook file is available for download here__.

.. __: https://github.com/zaphB/freecad.optics_design_workbench/tree/master/examples/1-getting-started/optimize-spotsize.ipynb


A more flexible way to sweep and optimize
-----------------------------------------






For detailed list of all available methods and arguments see the API reference of the class discussed in the this section:

.. currentmodule:: optics_design_workbench.jupyter_utils
.. autosummary:: 
  :toctree: api

  ParameterSweeper



:Footnotes:

  .. [#] I agree that this workflow is a little awkward and having to 
    wait for the FreeCAD startup every time you open the GUI 
    is annoying. The best solution would of course be be to have jupyter notebook and FreeCAD GUI open in parallel and keep all changes in sync between both. This challenging for technical reasons but will hopefully be implemented in the future.
