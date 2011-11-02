#!/usr/bin/python
# -*- coding: utf-8 -*-

# pylint: disable=C0111

# The dbmodel package provides an interface to the data required by the
# computational core of the lizard waterbalance Django app. This data is stored
# in multiple databases.
#
# Copyright (C) 2011 Nelen & Schuurmans
#
# This package is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version.
#
# This library is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# this package.  If not, see <http://www.gnu.org/licenses/>.

import logging

from lizard_waterbalance.models import IncompleteData
from lizard_waterbalance.models import PumpingStation
from timeseries.timeseriesstub import add_timeseries
from timeseries.timeseriesstub import TimeseriesRestrictedStub
from timeseries.timeseriesstub import TimeseriesWithMemoryStub

logger = logging.getLogger(__name__)

class Area(object):

    def __init__(self, configuration):

        self.configuration = configuration

    @property
    def surface(self):
        """Return the surface of the current Area in [m2]."""
        return self.configuration.open_water.surface

    @property
    def bottom_height(self):
        """Return the bottom height of the current Area in [mNAP]."""
        return self.configuration.open_water.bottom_height

    @property
    def init_water_level(self):
        """Return the initial water level of the current Area in [mNAP]."""
        return self.configuration.open_water.init_water_level

    @property
    def max_intake(self):
        """Return the max capacity of an intake of the current Area in [mNAP].

        The intake should be an intake for level control.

        """
        max_discharge = 0.0
        is_none = True
        for station in self.pumping_stations.filter(into=True, computed_level_control=True):
            if station.max_discharge is not None:
               max_discharge += station.max_discharge
               is_none = False

        if is_none:
            return None
        else:
            return max_discharge

    @property
    def max_outlet(self):
        """Return the max capacity of a pump of the current Area in [mNAP].

        The intake should be a pump for level control.

        """
        max_discharge = 0.0
        is_none = True
        for station in self.pumping_stations.filter(into=False, computed_level_control=True):
            if station.max_discharge is not None:
               max_discharge += station.max_discharge
               is_none = False

        if is_none:
            return None
        else:
            return max_discharge

    @property
    def buckets(self):
        """Return the Bucket(s) for the current Area."""
        return self.configuration.open_water.buckets.all()

    @property
    def pumping_stations(self):
        """Return the PumpingStation(s) for the current Area."""
        open_water = self.configuration.open_water
        return PumpingStation.objects.filter(open_water=open_water)

    def retrieve_precipitation(self, start_date, end_date):
        """Return the precipitation time series for the current Area.

        In case no precipitation time series is defined, this method throws an
        IncompleteData exception.

        """
        open_water = self.configuration.open_water
        if open_water.precipitation is None:
            exception_msg = "No precipitation is defined for the " \
                "waterbalance area %s" % unicode(open_water)
            logger.warning(exception_msg)
            raise IncompleteData(exception_msg)
        timeseries = open_water.precipitation.get_timeseries()
        return TimeseriesRestrictedStub(timeseries=timeseries,
                                        start_date=start_date,
                                        end_date=end_date)

    def retrieve_evaporation(self, start_date, end_date):
        """Return the evaporation time series for the current Area.

        In case no evaporation time series is defined, this method throws an
        IncompleteData exception.

        """
        open_water = self.configuration.open_water
        if open_water.evaporation is None:
            exception_msg = "No evaporation is defined for the waterbalance " \
                "area %s" % unicode(open_water)
            logger.warning(exception_msg)
            raise IncompleteData(exception_msg)
        timeseries = open_water.evaporation.get_timeseries()
        return TimeseriesRestrictedStub(timeseries=timeseries,
                                        start_date=start_date,
                                        end_date=end_date)

    def retrieve_seepage(self, start_date, end_date):
        """Return the seepage time series for the current Area.

        In case no seepage time series is defined, this method throws an
        IncompleteData exception.

        """
        open_water = self.configuration.open_water
        if open_water.seepage is None:
            exception_msg = "No seepage is defined for the waterbalance " \
                            "area %s" %  unicode(open_water)
            logger.warning(exception_msg)
            raise IncompleteData(exception_msg)
        timeseries = open_water.seepage.get_timeseries()
        return TimeseriesRestrictedStub(timeseries=timeseries,
                                        start_date=start_date,
                                        end_date=end_date)

    def retrieve_sewer(self, start_date, end_date):
        """Return the sewer time series for the current Area.

        It is possible no sewer time series has been defined. In that case,
        this method will return None.

        """
        open_water = self.configuration.open_water
        if open_water.sewer is None:
            return None

        timeseries = open_water.sewer.get_timeseries()
        return TimeseriesRestrictedStub(timeseries=timeseries,
                                        start_date=start_date,
                                        end_date=end_date)

    def retrieve_minimum_level(self, start_date, end_date):
        """Return the minimum water level for the current Area."""
        open_water = self.configuration.open_water
        if open_water.use_min_max_level_relative_to_meas:
             min_level = TimeseriesWithMemoryStub()
             min_level.add_value(start_date, open_water.min_level_relative_to_measurement)
             return add_timeseries(min_level, open_water.waterlevel_measurement.get_timeseries())
        else:
            return TimeseriesRestrictedStub(timeseries=open_water.minimum_level.get_timeseries(),
                                            start_date=start_date,
                                            end_date=end_date)

    def retrieve_maximum_level(self, start_date, end_date):
        """Return the maximum water level for the current Area."""
        open_water = self.configuration.open_water
        if open_water.use_min_max_level_relative_to_meas:
             max_level = TimeseriesWithMemoryStub()
             max_level.add_value(start_date, open_water.max_level_relative_to_measurement)
             return add_timeseries(max_level, open_water.waterlevel_measurement.get_timeseries())
        else:
            return TimeseriesRestrictedStub(timeseries=open_water.maximum_level.get_timeseries(),
                                        start_date=start_date,
                                        end_date=end_date)


    def retrieve_nutricalc_min(self, start_date, end_date):
        """Return the minimal nutricalc time series for the current Area.

        If no such time series is defined, this method returns None.

        """
        open_water = self.configuration.open_water
        if open_water.nutricalc_min is not None:
            timeseries = open_water.nutricalc_min.get_timeseries()
            return TimeseriesRestrictedStub(timeseries=timeseries,
                                            start_date=start_date,
                                            end_date=end_date)
        else:
            return None

    def retrieve_nutricalc_incr(self, start_date, end_date):
        """Return the incremental nutricalc time series for the current Area.

        If no such time series is defined, this method returns None.

        """
        open_water = self.configuration.open_water
        if open_water.nutricalc_incr is not None:
            timeseries = open_water.nutricalc_incr.get_timeseries()
            return TimeseriesRestrictedStub(timeseries=timeseries,
                                            start_date=start_date,
                                            end_date=end_date)
        else:
            return None

