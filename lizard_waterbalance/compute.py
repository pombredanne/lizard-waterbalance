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
# Copyright 2010 Nelen & Schuurmans
#
#******************************************************************************
#
# Initial programmer: Pieter Swinkels
# Initial date:       2010-11-26
#
#******************************************************************************

from datetime import datetime
from datetime import timedelta

import logging

from lizard_waterbalance.models import Bucket
from lizard_waterbalance.timeseriesstub import add_timeseries
from lizard_waterbalance.timeseriesstub import multiply_timeseries
from lizard_waterbalance.timeseriesstub import split_timeseries
from lizard_waterbalance.timeseriesstub import subtract_timeseries
from lizard_waterbalance.timeseriesstub import TimeseriesStub

class BucketOutcome:
    """Stores the time series that are computed for a Bucket.

    Instance variables:
    * storage -- time series for *berging*
    * flow_off -- time series for *afstroming*
    * net_drainage -- time series for *drainage* and *intrek*
    * seepage -- time series for *kwel*

    The value of a net_drainage event is positive when there is water coming
    into the bucket and negatice when there is water going out of the bucket.

    """
    def __init__(self):

        self.storage = TimeseriesStub()
        self.flow_off = TimeseriesStub()
        self.net_drainage = TimeseriesStub()
        self.seepage = TimeseriesStub()
        self.net_precipitation = TimeseriesStub()

    def name2timeseries(self):
        return {"storage": self.storage,
                "flow_off": self.flow_off,
                "net_drainage": self.net_drainage,
                "seepage": self.seepage,
                "net_precipitation": self.net_precipitation}

class SingleDayBucketsSummary:
    """Stores the interesting values of a single day summed over all buckets.

    Instance variables:
    * hardened -- single day value of *Qsom verhard*
    * drained -- single day value of *Qsom gedraineerdonder*
    * undrained -- single day value of *Qsom ongedraineerd*
    * flow off -- single day value of *Qsom afst*
    * infiltration -- single day of *Qsom intrek*

    """
    def total(self):
        return self.hardened +\
               self.drained +\
               self.undrained +\
               self.flow_off +\
               self.infiltration

class BucketsTotals:
    """Stores the total time series computed for all buckets.

    Instance variables:
    * hardened -- time series for *Qsom verhard*
    * drained -- time series for *Qsom gedraineerdonder*
    * undrained -- time series for *Qsom ongedraineerd*
    * flow off -- time series for *Qsom afst*
    * intake -- time series for *Qsom inlaat*
    * infiltration -- time series for *Qsom intrek*

    """
    def __init__(self):
        self.hardened = TimeseriesStub()
        self.drained = TimeseriesStub()
        self.undrained = TimeseriesStub()
        self.flow_off = TimeseriesStub()
        self.intake = TimeseriesStub()
        self.infiltration = TimeseriesStub()

class OpenWaterOutcome:
    """Stores the time series that are computed for an OpenWater.

    Instance variables:
    * precipitation -- time series for *neerslag*
    * evaporation -- time series for *verdamping*

    """
    def __init__(self):
        self.precipitation = TimeseriesStub()
        self.evaporation = TimeseriesStub()
        self.seepage = TimeseriesStub()

    def name2timeseries(self):
        return {"precipitation": self.precipitation,
                "evaporation": self.evaporation,
                "seepage": self.seepage}

def compute_seepage(bucket, seepage):
    """Return the seepage of the given bucket on the given date.

    Parameters:
    * bucket -- bucket for which to compute the seepage
    * date -- date for which to compute the seepage
    * seepage -- seepage in [mm/day]

    """
    # with regard to the factor 0.001 in the next line, seepage is specified
    # in [mm/day] but surface in [m]: 1 [mm] == 0.001 [m]
    return (bucket.surface * seepage) / 1000.0


def compute_net_precipitation(bucket,
                              previous_volume,
                              precipitation,
                              evaporation):
    """Return the net precipitation of today.

    With net precipitation, we mean the volume difference caused by
    precipitation and evaporation.

    Parameters:
    * bucket -- bucket for which to compute the net precipitation
    * previous_volume -- water volume of the bucket the day before
    * precipitation -- precipitation of today in [mm/day]
    * evaporation -- evaporation of today in [mm/day]

    """
    equi_volume = bucket.equi_water_level * bucket.surface
    if previous_volume > equi_volume:
        evaporation_factor = bucket.crop_evaporation_factor
    else:
        evaporation_factor = bucket.min_crop_evaporation_factor

    net_precipitation = precipitation - evaporation * evaporation_factor
    # with regard to the factor 0.001 in the next line, precipitation and
    # evaporation are specified in [mm/day] but surface in [m]: 1 [mm] == 0.001
    # [m]
    return net_precipitation * bucket.surface / 1000.0


def compute_net_drainage(bucket, previous_volume):
    """Return the net drainage of today.

    With net drainage, we mean the volume difference caused by drainage and
    infiltration.

    Parameters:
    * bucket -- bucket for which to compute the net drainage
    * previous_volume -- water volume of the bucket the day before

    """
    equi_volume = bucket.equi_water_level * bucket.surface
    if previous_volume > equi_volume:
        net_drainage = -previous_volume * bucket.drainage_fraction
    elif previous_volume < equi_volume:
        net_drainage = -previous_volume * bucket.infiltration_fraction
    else:
        net_drainage = 0
    return net_drainage

def compute(bucket, previous_storage, precipitation, evaporation, seepage):
    """Compute and return the waterbalance of the given bucket.

    This method computes for the given bucket the water storage, flow off, net
    drainage, seepage and net precipitation and returns them as a quintuple.

    Parameters:
    * bucket -- bucket for which to compute the waterbalance
    * previous_storage -- water storage of the bucket the day before in [m3]
    * precipitation -- precipitation time series for the bucket in [mm/day]
    * evaporation -- evaporation time series for the bucket in [mm/day]
    * seepage -- seepage time series for the bucket in [mm/day]

    """
    net_precipitation = compute_net_precipitation(bucket, previous_storage,
                                                  precipitation, evaporation)
    net_drainage = compute_net_drainage(bucket, previous_storage)
    seepage = compute_seepage(bucket, seepage)

    storage = previous_storage + net_precipitation + net_drainage + seepage
    max_storage = bucket.max_water_level * bucket.surface * bucket.porosity
    if storage > max_storage:
        flow_off = max_storage - storage
        storage = max_storage
    else:
        flow_off = 0

    return (storage, flow_off, net_drainage, seepage, net_precipitation)

def enumerate_events(*timeseries_list):

    latest_start = datetime.min
    for timeseries in timeseries_list:
        start = next((event[0] for event in timeseries.events()), None)
        assert not start is None
        latest_start = max(latest_start, start)

    new_timeseries_list = []
    for timeseries in timeseries_list:
        event_generator = (e for e in timeseries.events() if e[0] >= latest_start)
        new_timeseries_list.append(event_generator)

    for timeseries_tuple in zip(*new_timeseries_list):
        yield timeseries_tuple

def compute_timeseries(bucket, precipitation, evaporation, seepage, compute):
    """Compute and return the waterbalance time series of the given bucket.

    This method computes for the given bucket the time series that can be
    stored in a BucketOutcome and returns them as a BucketOutcome.

    Parameters:
    * bucket -- bucket for which to compute the waterbalance
    * precipitation -- precipitation time series in [mm/day]
    * evaporation -- evaporation time series  in [mm/day]
    * seepage -- seepage time series in [mm/day]
    * compute -- function to compute the daily waterbalance

    """
    outcome = BucketOutcome()
    volume = bucket.init_water_level * bucket.surface
    for triple in enumerate_events(precipitation, evaporation, seepage):
        precipitation_event = triple[0]
        event_date = precipitation_event[0]
        evaporation_event = triple[1]
        seepage_event = triple[2]
        bucket_triple = compute(bucket, volume, precipitation_event[1],
                                evaporation_event[1], seepage_event[1])
        #note that bucket_triple is a quintuple now
        volume = bucket_triple[0]
        outcome.storage.add_value(event_date, volume)
        outcome.flow_off.add_value(event_date, bucket_triple[1])
        outcome.net_drainage.add_value(event_date, bucket_triple[2])
        outcome.seepage.add_value(event_date, bucket_triple[3])
        outcome.net_precipitation.add_value(event_date, bucket_triple[4])
    return outcome

def compute_timeseries_on_hardened_surface(bucket, precipitation, evaporation, seepage, compute):

    # we first compute the upper bucket:
    #   - the upper bucket does not have seepage and does not have net drainage
    #   - the porosity of the upper bucket is always 1.0
    upper_seepage = TimeseriesStub()
    bucket.porosity, tmp = 1.0, bucket.porosity
    upper_outcome = compute_timeseries(bucket,
                                       precipitation,
                                       evaporation,
                                       upper_seepage,
                                       compute)
    bucket.porosity = tmp

    # we then compute the lower bucket:
    #  - the lower bucket does not have precipitation, evaporation and does not
    #    have flow off
    lower_precipitation = TimeseriesStub()
    lower_evaporation = TimeseriesStub()
    lower_outcome = compute_timeseries(bucket,
                                       lower_precipitation,
                                       lower_evaporation,
                                       seepage,
                                       compute)

    outcome = BucketOutcome()
    outcome.storage = upper_outcome.storage
    outcome.flow_off = upper_outcome.flow_off
    outcome.net_drainage = lower_outcome.net_drainage
    outcome.seepage = lower_outcome.seepage
    outcome.net_precipitation = upper_outcome.net_precipitation
    return outcome

def compute_timeseries_on_drained_surface(bucket, precipitation, evaporation, seepage, compute):

    # we first compute the upper bucket:
    #   - the upper bucket does not have seepage
    #   - the upper bucket has some of its own attributes
    upper_seepage = TimeseriesStub()

    bucket.porosity, bucket.upper_porosity = bucket.upper_porosity, bucket.porosity
    bucket.crop_evaporation_factor, bucket.upper_crop_evaporation_factor = bucket.upper_crop_evaporation_factor, bucket.crop_evaporation_factor
    bucket.min_crop_evaporation_factor, bucket.upper_min_crop_evaporation_factor = bucket.upper_min_crop_evaporation_factor, bucket.min_crop_evaporation_factor
    upper_outcome = compute_timeseries(bucket,
                                       precipitation,
                                       evaporation,
                                       upper_seepage,
                                       compute)
    bucket.porosity, bucket.upper_porosity = bucket.upper_porosity, bucket.porosity
    bucket.crop_evaporation_factor, bucket.upper_crop_evaporation_factor = bucket.upper_crop_evaporation_factor, bucket.crop_evaporation_factor
    bucket.min_crop_evaporation_factor, bucket.upper_min_crop_evaporation_factor = bucket.upper_min_crop_evaporation_factor, bucket.min_crop_evaporation_factor

    # we then compute the lower bucket:
    #  - the lower bucket does not have precipitation, evaporation and does not
    #    have flow off
    lower_precipitation = add_timeseries(upper_flow_off, upper_net_drainage)
    lower_evaporation = TimeseriesStub()
    lower_outcome = compute_timeseries(bucket,
                                       lower_precipitation,
                                       lower_evaporation,
                                       seepage,
                                       compute)

    outcome = BucketOutcome()
    outcome.storage = upper_outcome.storage
    outcome.flow_off = upper_outcome.flow_off
    outcome.net_drainage = lower_outcome.net_drainage
    outcome.seepage = lower_outcome.seepage
    outcome.net_precipitation = upper_outcome.net_precipitation
    return outcome

def retrieve_net_intake(open_water):

    incoming_timeseries = TimeseriesStub()
    for timeseries in open_water.retrieve_incoming_timeseries():
        incoming_timeseries = add_timeseries(incoming_timeseries, timeseries)

    outgoing_timeseries = TimeseriesStub()
    for timeseries in open_water.retrieve_outgoing_timeseries():
        outgoing_timeseries = add_timeseries(outgoing_timeseries, timeseries)

    return subtract_timeseries(incoming_timeseries, outgoing_timeseries)

def open_water_compute(open_water,
                       buckets,
                       bucket_computers,
                       pumping_stations,
                       timeseries_retriever):
    """Compute and return the waterbalance.

    Parameters:
    * open_water -- open water for which to compute the waterbalance
    * buckets -- list of buckets connected to the open water
    * bucket_computers -- dictionary of bucket surface type to function
    * pumping_stations -- list of stations that pump water into or out of the open water
    * timeseries_retriever -- object to retrieve the input time series

    Return value:
    * result -- dictionary of bucket and open water name to time series name
    to time series

    The input time series are precipitation, evaporation and seepage.

    """
    result = {}

    precipitation = timeseries_retriever.get_timeseries("precipitation")
    evaporation = timeseries_retriever.get_timeseries("evaporation")
    seepage = timeseries_retriever.get_timeseries("seepage")

    for bucket in buckets:
        bucket_computer = bucket_computers[bucket.surface_type]
        outcome = bucket_computer(bucket, precipitation, evaporation, seepage, compute)
        result[bucket.name] = outcome

    # [<open-water-name>]['precipitation'] to TimeseriesStub
    # [<open-water-name>]['evaporation'] to TimeseriesStub
    # [<open-water-name>]['sum hardened flow_off'] to TimeseriesStub
    # [<open-water-name>]['sum drained flow_off + net_drainage'] to TimeseriesStub
    # [<open-water-name>]['sum hardened net_drainage and undrained net_drainage'] to TimeseriesStub
    # [<open-water-name>]['sum undrained flow_off'] to TimeseriesStub
    # [<open-water-name>]['sum intake'] to TimeseriesStub
    # [<open-water-name>]['sum infiltration'] to TimeseriesStub
    # [<open-water-name>]['sum seepage'] to TimeseriesStub
    # [<open-water-name>]['sum sluice error'] to TimeseriesStub

    outcome = result.setdefault(open_water.name, OpenWaterOutcome())

    if precipitation:
        result[open_water.name].precipitation = multiply_timeseries(precipitation, open_water.surface / 1000.0)
    if evaporation:
        result[open_water.name].evaporation = multiply_timeseries(evaporation, -open_water.surface * open_water.crop_evaporation_factor / 1000.0)
    if seepage:
        result[open_water.name].seepage = multiply_timeseries(seepage, open_water.surface / 1000.0)

    return result


class WaterbalanceComputer:

    def __init__(self, buckets_computer=None, buckets_totals_computer=None,
                 level_control_computer=None):
        if buckets_computer is None:
            self.buckets_computer = BucketsComputer()
        else:
            self.buckets_computer = buckets_computer
        if buckets_totals_computer is None:
            self.buckets_totals_computer = BucketsTotalsComputer()
        else:
            self.buckets_totals_computer = buckets_totals_computer
        if level_control_computer is None:
            self.level_control_computer = LevelControlComputer()
        else:
            self.level_control_computer = level_control_computer

    def compute(self, area, start_date, end_date):
        """Return all waterbalance related time series for the given area.

        Paramaters:
        * area -- WaterbalanceArea for which to compute the time series
        * start_date -- first date of the time window (for ...)
        * end_date -- day after the last date of the time window (for ...)

        """
        precipitation = area.retrieve_precipitation(start_date, end_date)
        evaporation = area.retrieve_evaporation(start_date, end_date)
        seepage = area.retrieve_seepage(start_date, end_date)
        buckets = area.retrieve_buckets()
        bucket2outcome = self.buckets_computer.compute(buckets,
                                                       precipitation,
                                                       evaporation,
                                                       seepage)
        level_control = self.level_control_computer.compute(start_date,
                                                            end_date,
                                                            area.open_water,
                                                            bucket2outcome,
                                                            precipitation,
                                                            evaporation,
                                                            seepage)
        # buckets_totals = self.buckets_totals_computer.compute(start_date,
        #                                                       end_date,
        #                                                       bucket2outcome)
        return (bucket2outcome, level_control)


class BucketsComputer:

    def __init__(self, bucket_computers=None):
        if bucket_computers is None:
            self.bucket_computers = {}
            self.bucket_computers[Bucket.UNDRAINED_SURFACE] = compute_timeseries
            self.bucket_computers[Bucket.HARDENED_SURFACE] = compute_timeseries_on_hardened_surface
            self.bucket_computers[Bucket.DRAINED_SURFACE] = compute_timeseries_on_drained_surface
        else:
            self.bucket_computers = bucket_computers

    def compute(self, buckets, precipitation, evaporation, seepage):
        """Compute and return the waterbalance for the given buckets.

        Parameters:
        * buckets -- list of buckets connected to the open water
        * precipitation -- TimesseriesStub for the precipitation
        * evaporation -- TimesseriesStub for the evaporation
        * seepage -- TimesseriesStub for the seepage

        Return value:
        * result -- dictionary of bucket to TimesseriesStub
        """
        result = {}
        for bucket in buckets:
            bucket_computer = self.bucket_computers[bucket.surface_type]
            outcome = bucket_computer(bucket, precipitation, evaporation, seepage, compute)
            result[bucket] = outcome
        return result


class BucketsTotalsComputer:

    def __init__(self, bucket_summarizer=None):
        if bucket_summarizer is None:
            self.bucket_summarizer = BucketSummarizer()
        else:
            self.bucket_summarizer = bucket_summarizer

    def compute(self, start_date, end_date, bucket2outcome):

        totals = BucketsTotals()

        date = start_date
        while date < end_date:
            for bucket, outcome in bucket2outcome.iteritems():
                daily_totals = self.bucket_summarizer.compute(date)
            totals.append(daily_totals)


class LevelControlComputer:

    def compute(self, start_date, end_date, open_water, bucket_outcomes,
                precipitation, evaporation, seepage):
        """Compute and return the pair of intake and pump time series.

        This function returns the pair of TimeseriesStub(s) that contains the
        intake time series and pump time series for the given open_water.

        Parameters:
        * open_water -- OpenWater for which to compute the level control time series
        * bucket_outcomes -- BucketOutcome(s) with the results of each bucket
        * precipitation -- TimeseriesStub with the precipitation in [mm/day]
        * evaporation -- TimeseriesStub with the evaporation in [mm/day]
        * seepage -- TimeseriesStub with the seepage in [mm/day]

        """
        result = TimeseriesStub()
        surface = open_water.surface
        water_level = open_water.init_water_level
        date = start_date
        while date < end_date:
            incoming_value = self.compute_incoming_volume(date,
                                                          surface,
                                                          open_water.crop_evaporation_factor,
                                                          water_level,
                                                          bucket_outcomes,
                                                          precipitation,
                                                          evaporation,
                                                          seepage)


            water_level += incoming_value / surface
            logging.debug("incoming_value (%.2f) / surface (%.2f) = %.2f" % (incoming_value, surface, incoming_value / surface))
            logging.debug("water_level = %.2f (uncorrected) " % water_level)
            level_control = self._compute_level_control(date, open_water,
                                                        surface, water_level)
            logging.debug("level_control = %.2f " % level_control)
            water_level += level_control / surface
            logging.debug("water_level = %.2f " % water_level)

            result.add_value(date, level_control)
            date += timedelta(1)
        (pump_time_series, intake_time_series) = split_timeseries(result)
        return (intake_time_series, pump_time_series)

    def compute_incoming_volume(self, date, surface, crop_evaporation_factor,
                                 water_level, bucket_outcomes, precipitation,
                                 evaporation, seepage):
        precipitation = precipitation.get_value(date) * surface
        evaporation = -evaporation.get_value(date) * surface * \
                      crop_evaporation_factor
        seepage = seepage.get_value(date) * surface
        incoming_volume = precipitation + evaporation + seepage
        summarizer = BucketSummarizer(bucket_outcomes)
        total = summarizer.compute(date).total()
        incoming_volume += total
        logging.debug("compute_incoming_volume on %s: %.2f (%.2f, %.2f, %.2f) %.2f" % (date.strftime("%Y-%m-%d"), incoming_volume * 0.001, precipitation, evaporation, seepage, total))
        # all aforementioned time series are specified in [mm/day] but we need
        # [m/day]: 1 [mm] = 0.001 [m]
        return incoming_volume * 0.001

    def _compute_level_control(self, date, open_water, surface, water_level):
        """Compute and return the level control for the given date.

        Parameters:
        * date -- date for which to compute the intake or pump value
        * open_water -- OpenWater for which to compute the level control time series
        * surface -- surface of the open water in [m2]
        * water_level -- uncorrected water level of the open water in [m]

        """
        minimum_water_level = open_water.retrieve_minimum_level().get_value(date)
        maximum_water_level = open_water.retrieve_maximum_level().get_value(date)
        logging.debug("minimum maximum water_level = %.2f %2f " % (minimum_water_level, maximum_water_level))
        if water_level > maximum_water_level:
            level_control = -(water_level - maximum_water_level) * surface
        elif water_level < minimum_water_level:
            level_control = (minimum_water_level - water_level) * surface
        else:
            level_control = 0
        return level_control


class BucketSummarizer:
    """Computes the SingleDayBucketsSummary.

    Instance variables:
    * bucket2outcome -- dictionary of Bucket to BucketOutcome
    """
    def __init__(self, bucket2outcome={}):
        """Set the dictionary of Bucket to BucketOutcome to the given one."""
        self.bucket2outcome = bucket2outcome

    def compute(self, date):
        """Compute and return the SingleDayBucketsSummary on the given date."""
        summary = SingleDayBucketsSummary()
        summary.hardened = self.compute_sum_hardened(date)
        summary.drained = self.compute_sum_drained(date)
        summary.undrained = self.compute_sum_undrained_net_drainage(date)
        summary.flow_off = self.compute_sum_undrained_flow_off(date)
        summary.infiltration = self.compute_sum_infiltration(date)
        return summary

    def compute_sum_hardened(self, date):
        sum = 0.0
        for bucket, outcome in self.bucket2outcome.iteritems():
            if bucket.surface_type == Bucket.HARDENED_SURFACE:
                sum += outcome.flow_off.get_value(date)
        return sum

    def compute_sum_drained(self, date):
        sum = 0.0
        for bucket, outcome in self.bucket2outcome.iteritems():
            if bucket.surface_type == Bucket.DRAINED_SURFACE:
                sum += outcome.flow_off.get_value(date)
                net_drainage = outcome.net_drainage.get_value(date)
                if net_drainage < 0:
                    sum += net_drainage
        return sum

    def compute_sum_undrained_net_drainage(self, date):
        sum = 0.0
        for bucket, outcome in self.bucket2outcome.iteritems():
            if bucket.surface_type == Bucket.HARDENED_SURFACE or \
               bucket.surface_type == Bucket.UNDRAINED_SURFACE:
                net_drainage = outcome.net_drainage.get_value(date)
                if net_drainage < 0:
                    sum += net_drainage
        return sum

    def compute_sum_undrained_flow_off(self, date):
        sum = 0.0
        for bucket, outcome in self.bucket2outcome.iteritems():
            if bucket.surface_type == Bucket.UNDRAINED_SURFACE:
                sum += outcome.flow_off.get_value(date)
        return sum

    def compute_sum_infiltration(self, date):
        sum = 0.0
        for bucket, outcome in self.bucket2outcome.iteritems():
            if bucket.surface_type == Bucket.UNDRAINED_SURFACE or \
               bucket.surface_type == Bucket.HARDENED_SURFACE or \
               bucket.surface_type == Bucket.DRAINED_SURFACE:
                net_drainage = outcome.net_drainage.get_value(date)
                if net_drainage > 0:
                    sum += net_drainage
        return sum


