"""Test an app as its phone runs it, with no phone.

``driver.AppDriver`` starts an app through the session a device runs, finds
controls in the snapshot it publishes and acts on them by the intents they
carry; ``simulator.Simulator`` replaces the runtime's scheduler with a virtual
clock, so timing tests take no time and repeat exactly.
"""

__version__ = "0.1.0"
