# -*- coding: utf-8 -*-
"""Graphical user interface to Amtron CS400 laser controller."""

import sys
import sip
from functools import partial
from operator import mul
for cls in "QDate QDateTime QString QTextStream QTime QUrl QVariant".split():
    sip.setapi(cls, 2)

from PyQt4 import QtCore, QtGui
Qt = QtCore.Qt

from pyhard2.gui.driver import DriverWidget
from pyhard2.gui.controller import Controller, Config
from pyhard2.gui.programs import SetpointRampProgram
import pyhard2.driver as drv
Cmd = drv.Command
import pyhard2.driver.virtual as virtual
import pyhard2.driver.amtron as amtron
import pyhard2.driver.daq as daq


class ButtonDelegate(QtGui.QAbstractItemDelegate):

    def __init__(self, parent=None):
        super(ButtonDelegate, self).__init__(parent)

    def setEditorData(self, editor, index):
        if not index.isValid():
            return
        editor.setChecked(index.data() is True)

    def setModelData(self, editor, model, index):
        if not index.isValid():
            return
        model.setData(index, editor.isChecked())


class AmtronDriverWidget(DriverWidget):

    def __init__(self, parent=None):
        super(AmtronDriverWidget, self).__init__(parent)
        self.powerBtn = QtGui.QPushButton("Power", checkable=True)
        self.gateBtn = QtGui.QPushButton("Gate", checkable=True)
        self.pilotBtn = QtGui.QPushButton("Pilot laser", checkable=True)
        self.buttonsLayout = QtGui.QHBoxLayout()
        self.buttonsLayout.addWidget(self.powerBtn)
        self.buttonsLayout.addWidget(self.gateBtn)
        self.buttonsLayout.addWidget(self.pilotBtn)
        self.verticalLayout.addLayout(self.buttonsLayout)

        self.powerBtnMapper = QtGui.QDataWidgetMapper(self)
        self.gateBtnMapper = QtGui.QDataWidgetMapper(self)
        self.pilotBtnMapper = QtGui.QDataWidgetMapper(self)
        self.powerBtnMapper.setItemDelegate(
            ButtonDelegate(self.powerBtnMapper))
        self.gateBtnMapper.setItemDelegate(
            ButtonDelegate(self.gateBtnMapper))
        self.pilotBtnMapper.setItemDelegate(
            ButtonDelegate(self.pilotBtnMapper))
        self.powerBtn.toggled.connect(self.powerBtnMapper.submit)
        self.gateBtn.toggled.connect(self.gateBtnMapper.submit)
        self.pilotBtn.toggled.connect(self.pilotBtnMapper.submit)

    def setDriverModel(self, model):
        super(AmtronDriverWidget, self).setDriverModel(model)
        self.powerBtnMapper.setModel(model)
        self.gateBtnMapper.setModel(model)
        self.pilotBtnMapper.setModel(model)

    def mapPowerStateEditor(self, column):
        assert(self.powerBtnMapper.model())
        self.powerBtnMapper.addMapping(self.powerBtn, column)

    def mapGateStateEditor(self, column):
        assert(self.gateBtnMapper.model())
        self.gateBtnMapper.addMapping(self.gateBtn, column)

    def mapPilotStateEditor(self, column):
        assert(self.pilotBtnMapper.model())
        self.pilotBtnMapper.addMapping(self.pilotBtn, column)


class AmtronController(Controller):

    def __init__(self, config, driver, parent=None):
        super(AmtronController, self).__init__(config, driver, parent)
        self.programs.default_factory = SetpointRampProgram
        self.populated.connect(self.driverWidget.powerBtnMapper.toFirst)
        self.populated.connect(self.driverWidget.gateBtnMapper.toFirst)
        self.populated.connect(self.driverWidget.pilotBtnMapper.toFirst)
        self._specialColumnMapper.update(dict(
            laserpower=self.setPowerStateColumn,
            lasergate=self.setGateStateColumn,
            pilotlaser=self.setPilotStateColumn
        ))

    def _addDriverWidget(self):
        super(AmtronController, self)._addDriverWidget(AmtronDriverWidget)

    def _currentRowChanged(self, current, previous):
        super(AmtronController, self)._currentRowChanged(current, previous)
        self.driverWidget.powerBtnMapper.setCurrentModelIndex(current)
        self.driverWidget.gateBtnMapper.setCurrentModelIndex(current)
        self.driverWidget.pilotBtnMapper.setCurrentModelIndex(current)

    def setPowerStateColumn(self, column):
        self.driverWidget.mapPowerStateEditor(column)

    def setGateStateColumn(self, column):
        self.driverWidget.mapGateStateEditor(column)

    def setPilotStateColumn(self, column):
        self.driverWidget.mapPilotStateEditor(column)


class AmtronDaq(drv.Subsystem):

    """Instrument using the DAQ for input (temperature) and the CS400
    for output (laser power).  Output is controller by a software PID.

    """
    # connections:
    #    thermometer      pid           laser
    #    measure      ->  compute   ->  output
    def __init__(self, serial, daqline):
        super(AmtronDaq, self).__init__()
        self.pid = virtual.PidSubsystem(self, spmin=-100.0, spmax=1000.0)
        self.temperature = daq.Daq(daqline)
        self.temperature.voltage.ai._rfunc = partial(mul, 100)
        self.laser = amtron.CS400(serial)
        self.laser.control.control_mode.write(amtron.ControlMode.POWER)
        self.laser.command.laser_state.write(False)
        # Connections
        self.temperature.voltage.ai.signal.connect(self.pid.measure.write)
        self.temperature.voltage.ai.signal.connect(
            lambda value, node: self.pid.output.read(node))
        self.pid.output.signal.connect(self.laser.control.total_power.write)


class _VirtualCommand(object):

    def __init__(self):
        self.laser_state = False
        self.gate_state = False


class _VirtualInterface(object):

    def __init__(self):
        self.pilot_laser_state = False


class VirtualAmtronInstrument(virtual.VirtualInstrument):

    def __init__(self):
        super(VirtualAmtronInstrument, self).__init__()
        self.laser = drv.Subsystem(self)
        self.laser.command = drv.Subsystem(self.laser)
        self.laser.command.setProtocol(
            drv.ObjectWrapperProtocol(_VirtualCommand()))
        self.laser.command.laser_state = Cmd("laser_state")
        self.laser.command.gate_state = Cmd("gate_state")
        self.laser.interface = drv.Subsystem(self.laser)
        self.laser.interface.setProtocol(
            drv.ObjectWrapperProtocol(_VirtualInterface()))
        self.laser.interface.pilot_laser_state = Cmd("pilot_laser_state")


def createController():
    """Initialize controller."""
    config = Config("amtron", "CS400")
    if not config.nodes:
        config.nodes, config.names = (["ai0"], ["CS400"])
    if config.virtual:
        driver = VirtualAmtronInstrument()
        iface = AmtronController.virtualInstrumentController(config, driver)
    else:
        driver = AmtronDaq(drv.Serial(config.port), "Circat1")
        iface = AmtronController(config, driver)
        iface.addCommand(driver.temperature.voltage.ai,
                         "temperature / C", poll=True, log=True)
        iface.addCommand(driver.pid.setpoint, "setpoint / C",
                         log=True, specialColumn="programmable")
        iface.addCommand(driver.laser.control.total_power, "power / W",
                         poll=True, log=True)
        iface.addCommand(driver.pid.proportional, "PID P", hide=True,
                         specialColumn="pidp")
        iface.addCommand(driver.pid.integral_time, "PID I", hide=True,
                         specialColumn="pidi")
        iface.addCommand(driver.pid.derivative_time, "PID D", hide=True,
                         specialColumn="pidd")
    iface.addCommand(driver.laser.command.laser_state, "power", hide=True,
                     poll=True, specialColumn="laserpower")
    iface.addCommand(driver.laser.command.gate_state, "gate", hide=True,
                     poll=True, specialColumn="lasergate")
    iface.addCommand(driver.laser.interface.pilot_laser_state, "pilot",
                     hide=True, poll=False, specialColumn="pilotlaser")
    iface.populate()
    return iface


def main(argv):
    """Start controller."""
    app = QtGui.QApplication(argv)
    app.lastWindowClosed.connect(app.quit)
    iface = createController()
    iface.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main(sys.argv)
