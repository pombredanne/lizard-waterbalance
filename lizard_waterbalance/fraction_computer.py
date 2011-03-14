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

from timeseries.timeseriesstub import enumerate_events
from timeseries.timeseriesstub import split_timeseries
from timeseries.timeseriesstub import TimeseriesStub


class FractionComputer:

    def compute(self, open_water, buckets_summary, vertical_timeseries,
                storage_timeseries, intakes_timeseries):
        """Compute and return the fraction series.

        This function returns the pair of TimeseriesStub(s) that consists of
        the intake time series and pump time series for the given open water.

        Parameters:
        * open_water -- OpenWater for which to compute the fractions
        * buckets_summary -- BucketsSummary with the summed buckets outcome
        * vertical_timeseries -- list of time series [precipitation,
          evaporation, seepage, infiltration], where each time series is
          specified in [m3/day]
        * storage_timeseries -- storage time series in [m3/day]
        * intakes_timeseries -- list of intake timeseries in [m3/day]

        """
        fractions_initial = TimeseriesStub()
        fractions_precipitation = TimeseriesStub()
        fractions_seepage = TimeseriesStub()
        fractions_hardened = TimeseriesStub()
        fractions_drained = TimeseriesStub()
        fractions_undrained = TimeseriesStub()
        fractions_flow_off = TimeseriesStub()
        fractions_intakes = [TimeseriesStub() for timeseries in intakes_timeseries]

        previous_initial = 1.0
        previous_precipitation = 0.0
        previous_seepage = 0.0
        previous_hardened = 0.0
        previous_drained = 0.0
        previous_undrained = 0.0
        previous_flow_off = 0.0
        previous_intakes = [0.0 for timeseries in intakes_timeseries]
        intakes = [0.0 for timeseries in intakes_timeseries]

        previous_storage = self.initial_storage(open_water)

        timeseries_list = []
        timeseries_list.append(buckets_summary.hardened)
        timeseries_list.append(buckets_summary.drained)
        timeseries_list.append(buckets_summary.undrained)
        timeseries_list.append(buckets_summary.flow_off)
        timeseries_list.append(buckets_summary.indraft)
        timeseries_list += vertical_timeseries
        timeseries_list.append(storage_timeseries)
        timeseries_list += intakes_timeseries

        self.index_hardened = 0
        self.index_drained = 1
        self.index_undrained = 2
        self.index_flow_off = 3
        self.index_indraft = 4
        self.index_precipitation = 5
        self.index_evaporation = 6
        self.index_seepage = 7
        self.index_infiltration = 8
        self.index_storage = 9

        for event_tuple in enumerate_events(*timeseries_list):
            date = event_tuple[0][0]
            event_values = [event[1] for event in event_tuple]

            initial = self.compute_fraction(event_values, previous_initial,
                                           previous_storage)

            precipitation = self.compute_fraction(event_values,
                                                  previous_precipitation,
                                                  previous_storage,
                                                  event_values[self.index_precipitation])

            seepage = self.compute_fraction(event_values,
                                            previous_seepage,
                                            previous_storage,
                                            event_values[self.index_seepage])

            hardened = self.compute_fraction(event_values,
                                             previous_hardened,
                                             previous_storage,
                                             event_values[self.index_hardened])

            drained = self.compute_fraction(event_values,
                                             previous_drained,
                                             previous_storage,
                                             event_values[self.index_drained])

            undrained = self.compute_fraction(event_values,
                                            previous_undrained,
                                            previous_storage,
                                            event_values[self.index_undrained])

            flow_off = self.compute_fraction(event_values,
                                             previous_flow_off,
                                             previous_storage,
                                             event_values[self.index_flow_off])

            if len(intakes_timeseries) > 0:
                for index, intake_timeserie in enumerate(intakes_timeseries):
                    intakes[index] = self.compute_fraction(event_values,
                                                           previous_intakes[index],
                                                           previous_storage,
                                                           event_values[self.index_storage + 1 + index])

            # Due to rounding errors, the sum of the fractions is seldom equal
            # to 1.0. As the fraction of the next day depends on the fraction
            # of the previous day, this effect gets worse over time. To avoid
            # this effect, we divide each fraction by the sum of fractions.

            total_fractions = initial + precipitation + seepage + hardened + \
                              drained + undrained + flow_off + sum(intakes)

            initial /= total_fractions
            precipitation /= total_fractions
            seepage /= total_fractions
            hardened /= total_fractions
            drained /= total_fractions
            undrained /= total_fractions
            flow_off /= total_fractions
            intakes = [intake / total_fractions for intake in intakes]

            fractions_initial.add_value(date, initial)
            previous_initial = initial
            fractions_precipitation.add_value(date, precipitation)
            previous_precipitation = precipitation
            fractions_seepage.add_value(date, seepage)
            previous_seepage = seepage
            fractions_hardened.add_value(date, hardened)
            previous_hardened = hardened
            fractions_drained.add_value(date, drained)
            previous_drained = drained
            fractions_undrained.add_value(date, undrained)
            previous_undrained = undrained
            fractions_flow_off.add_value(date, flow_off)
            previous_flow_off = flow_off

            if len(intakes_timeseries) > 0:
                for index, intake_timeserie in enumerate(intakes_timeseries):
                    fractions_intakes[index].add_value(date, intakes[index])
                    previous_intakes[index] = intakes[index]

            previous_storage = event_values[self.index_storage]


        return [fractions_initial,
                fractions_precipitation,
                fractions_seepage,
                fractions_hardened,
                fractions_drained,
                fractions_undrained,
                fractions_flow_off] + fractions_intakes

    def compute_fraction(self, event_values, previous_fraction, previous_storage,
                        additional_term=None):
        incoming = self.total_incoming(event_values)
        if abs(previous_storage + incoming) < 1e-6:
            if additional_term is None:
                fraction = 1.0
            else:
                fraction = 0.0
        else:
            if additional_term is None:
                additional_term = 0.0
            fraction = previous_fraction * previous_storage + additional_term
            fraction /= (previous_storage + incoming)
        return fraction

    def initial_storage(self, open_water):
        return 1.0 * open_water.surface * \
               (open_water.init_water_level - open_water.bottom_height)

    def total_incoming(self, event_values):
        incoming_values = event_values[:]
        del incoming_values[self.index_storage]
        del incoming_values[self.index_indraft]
        return sum(incoming_values)

