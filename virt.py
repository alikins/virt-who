"""
Module for accessing libvirt, part of virt-who

Copyright (C) 2011 Radek Novacek <rnovacek@redhat.com>

This program is free software; you can redistribute it and/or
modify it under the terms of the GNU General Public License
as published by the Free Software Foundation; either version 2
of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program; if not, write to the Free Software
Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.
"""

import libvirt
import event

class VirtError(Exception):
    pass


class HypervisorInfoModel(dict):

    @classmethod
    def fromVirConnect(cls, virConnect):
        virt_type = virConnect.getType()
        #virt_caps = virConnect.getCapabilities()

        host = cls()
        host['hypervisorType'] = virt_type
        #host['hypervisorCaps'] = virt_caps
        return host


class GuestIdModel(dict):

    @classmethod
    def fromDomain(cls, domain):
        guestUUID = domain.UUIDString()
        attrs = {}
        attrs['active'] = domain.isActive()

        guestId = cls()
        guestId['guestId'] = guestUUID
        guestId['attributes'] = attrs
        return guestId


class Virt:
    """ Class for interacting with libvirt. """
    def __init__(self, logger, registerEvents=True):
        self.changedCallback = None
        self.logger = logger
        self.virt = None

        # Log libvirt errors
        libvirt.registerErrorHandler(lambda ctx, error: None, None) #self.logger.exception(error), None)
        try:
            self.virt = libvirt.openReadOnly("")
            # Register listener for domain changes if we are not in oneshot mode
            if registerEvents:
                self.virt.domainEventRegister(self.changed, None)
                event.virtType = self.virt.getType()
        except libvirt.libvirtError, e:
            raise VirtError(str(e))


    def listDomains(self):
        """ Get list of all domains. """
        domains = []

        hypervisorInfo = HypervisorInfoModel.fromVirConnect(self.virt)

        try:
            # Active domains
            for domainID in self.virt.listDomainsID():
                domain = self.virt.lookupByID(domainID)
                if domain.UUIDString() == "00000000-0000-0000-0000-000000000000":
                    # Don't send Domain-0 on xen (zeroed uuid)
                    continue
                guest = GuestIdModel.fromDomain(domain)
                guest['attributes'].update(hypervisorInfo)

                domains.append(guest)
                self.logger.debug("Virtual machine found: %s: %s %s" % (domain.name(), domain.UUIDString(), guest))

            # Non active domains
            for domainName in self.virt.listDefinedDomains():
                domain = self.virt.lookupByName(domainName)

                guest = GuestIdModel.fromDomain(domain)
                guest['attributes'].update(hypervisorInfo)

                domains.append(guest)
                self.logger.debug("Virtual machine found: %s: %s %s" % (domainName, domain.UUIDString(), guest))
        except libvirt.libvirtError, e:
            raise VirtError(str(e))
        return domains

    def __del__(self):
        if self.virt:
            self.virt.close()

    def changed(self, conn, dom, event, detail, opaque):
        self.logger.debug("EVENT: Domain %s(%s) %s %s" % (dom.name(), dom.ID(), eventToString(event), detailToString(event, detail)))
        if self.changedCallback:
            l = self.listDomains()
            uuid = dom.UUIDString()
            # Workaround: xen sometimes doesn't update domain list when the event happens, add/remove the
            # affected domain manually
            if event == libvirt.VIR_DOMAIN_EVENT_UNDEFINED:
                # Copy the list of domains without deleted domain
                l = [d for d in l if d.UUIDString() != uuid]
            elif event == libvirt.VIR_DOMAIN_EVENT_DEFINED:
                # Add domain if not already added
                hasDomain = False
                for d in l:
                    if d.UUIDString() == uuid:
                        hasDomain = True
                        break
                if not hasDomain:
                    l.append(dom)
            try:
                self.changedCallback(l)
            except Exception, e:
                self.logger.exception("Updating consumer failed:")

    def domainEventRegisterCallback(self, callback):
        self.changedCallback = callback

    def ping(self):
        try:
            self.virt.getVersion()
            return True
        except Exception:
            return False


def eventToString(event):
    eventStrings = ( "Defined",
                     "Undefined",
                     "Started",
                     "Suspended",
                     "Resumed",
                     "Stopped",
                     "Shutdown"
                   )
    try:
        return eventStrings[event]
    except IndexError:
        return "Unknown (%d)" % event

def detailToString(event, detail):
    eventStrings = (
        ( "Added", "Updated" ), # Defined
        ( "Removed", ), # Undefined
        ( "Booted", "Migrated", "Restored", "Snapshot", "Wakeup" ), # Started
        ( "Paused", "Migrated", "IOError", "Watchdog", "Restored", "Snapshot" ), # Suspended
        ( "Unpaused", "Migrated", "Snapshot" ), # Resumed
        ( "Shutdown", "Destroyed", "Crashed", "Migrated", "Saved", "Failed", "Snapshot" ), # Stopped
        ( "Finished", ), # Shutdown
        )
    try:
        return eventStrings[event][detail]
    except IndexError:
        return "Unknown (%d)" % detail
