#!/usr/bin/python
# -*- coding: utf-8 -*-
#******************************************************************************
#
# This file is part of the lizard_waterbalance Django app.
#
# The lizard_waterbalance app is free software: you can redistribute it and/or
# modify it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version.
#
# This library is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# the lizard_waterbalance app.  If not, see <http://www.gnu.org/licenses/>.
#
# Copyright 2011 Nelen & Schuurmans
#
#******************************************************************************
#
# Initial programmer: Pieter Swinkels
#
#******************************************************************************

from datetime import timedelta

from lizard_waterbalance.timeseriesstub import enumerate_events
from lizard_waterbalance.timeseriesstub import split_timeseries
from lizard_waterbalance.timeseriesstub import TimeseriesStub


class LevelControlComputer:

    def compute(self, open_water, buckets_summary,
                minimum_level_timeseries, maximum_level_timeseries,
                intakes_timeseries, pumps_timeseries, precipitation,
                evaporation, seepage):
        """Compute and return the pair of intake and pump time series.

        This function returns the pair of TimeseriesStub(s) that consists of
        the intake time series and pump time series for the given open water.

        Parameters:
        * open_water -- OpenWater for which to compute the level control
        * buckets_summary -- BucketsSummary with the summed buckets outcome
        * intakes_timeseries -- list of intake timeseries in [m3/day]
        * pumps_timeseries -- list of pump timeseries in [m3/day]
        * precipitation -- precipitation time series in [mm/day]
        * evaporation -- evaporation time series in [mm/day]
        * seepage -- seepage time series in [mm/day]

        """
        result = TimeseriesStub()
        surface = 1.0 * open_water.surface
        water_level = open_water.init_water_level

        timeseries_list = []
        timeseries_list += [buckets_summary.totals]
        timeseries_list += [precipitation]
        timeseries_list += [evaporation]
        timeseries_list += [seepage]
        timeseries_list += [minimum_level_timeseries]
        timeseries_list += [maximum_level_timeseries]
        timeseries_list += intakes_timeseries[:]
        timeseries_list += pumps_timeseries[:]

        index_first_pump_event = len(timeseries_list) - len(pumps_timeseries)
        for event_tuple in enumerate_events(*timeseries_list):
            date = event_tuple[0][0]
            buckets_total_value = event_tuple[0][1]
            precipitation_value = event_tuple[1][1]
            evaporation_value = event_tuple[2][1]
            seepage_value = event_tuple[3][1]
            minimum_level = event_tuple[4][1]
            maximum_level = event_tuple[5][1]
            incoming_value = self.compute_incoming_volume(surface,
                                                          open_water.crop_evaporation_factor,
                                                          water_level,
                                                          buckets_total_value,
                                                          precipitation_value,
                                                          evaporation_value,
                                                          seepage_value)

            water_level += incoming_value / surface
            for intake_event in event_tuple[6:index_first_pump_event]:
                water_level += intake_event[1] / surface
            for pump_event in event_tuple[index_first_pump_event:]:
                water_level -= pump_event[1] / surface
            level_control = self._compute_level_control(surface, water_level, minimum_level, maximum_level)
            water_level += level_control / surface

            result.add_value(date, level_control)
            date += timedelta(1)
        (pump_time_series, intake_time_series) = split_timeseries(result)
        return (intake_time_series, pump_time_series)

    def compute_incoming_volume(self, surface, crop_evaporation_factor,
                                 water_level, buckets_value, precipitation_value,
                                 evaporation_value, seepage_value):
        incoming_volume = buckets_value
        precipitation = precipitation_value * surface
        evaporation = -evaporation_value * surface * \
                      crop_evaporation_factor
        seepage = seepage_value * surface
        incoming_volume += precipitation + evaporation + seepage
        # all aforementioned time series are specified in [mm/day] but we need
        # [m/day]: 1 [mm] = 0.001 [m]
        return incoming_volume * 0.001

    def _compute_level_control(self, surface, water_level, minimum_water_level, maximum_water_level):
        """Compute and return the level control for the given date.

        Parameters:
        * surface -- surface of the open water in [m2]
        * water_level -- uncorrected water level of the open water in [m]
        * minimum_water_level -- minimum allowed water level
        * maximum_water_level -- maximum allowed water level

        """
        if water_level > maximum_water_level:
            level_control = -(water_level - maximum_water_level) * surface
        elif water_level < minimum_water_level:
            level_control = (minimum_water_level - water_level) * surface
        else:
            level_control = 0
        return level_control