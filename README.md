# Optics Design Workbench

This workbench was inspired by the (OpticsWorkbench)[https://github.com/chbergmann/OpticsWorkbench] by Christian Bergmann.


## Installation



Because running `import freecad.something` causes a Segfault in many python interpreters, the workbench installs both the `freecad.optics_design_workbench` module and an identical `freecad_.optics_design_workbench` module. The latter can always be safely imported to use the parts of the module that are not related to FreeCAD.


## Parallel computing

The GUI simulations all take place in the GUI main thread using the "QApplication.processEvents" hack to keep the GUI responsive. The extra implementation work for a proper QRunnable/QThreadpool solution is not worth it (yet), because it would only improve the responsivenes, not the actual simulation performance because of python's GIL.

To do simulations with actual performance gain, background processes running headless FreeCADCmd are launched in the background.


## Module structure

### `distributions`

Classes and functions for (random) point generation following given distributions.


### `freecad_elements` 

Contains all definitions for behavior/objects/commands living in the FreeCAD projects. The ray-tracing code is in here, because it is inherently connected to the FreeCAD geometry engine.


### `gui_windows`

Contains classes/functions that open additional windows.


### `simulation`

Contains classes/functions handling the simulation loop, saving of results, progress tracking, background workers, etc. Submodules in here use the FreeCAD.App and Gui objects in a few places but only to fetch paths or similar metadata, not for direct interaction. For direct interaction prefer to use submodules of freecad_elements.
