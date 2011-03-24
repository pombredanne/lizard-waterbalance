# (c) Nelen & Schuurmans.  GPL licensed, see LICENSE.txt.

# Create your views here.

import datetime
import logging
import time

from django.contrib import messages
from django.core.urlresolvers import reverse
from django.core.cache import cache
from django.http import HttpResponse
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.shortcuts import render_to_response
from django.template import RequestContext
from django.utils import simplejson
from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvas
from matplotlib.lines import Line2D
import mapnik
import pkg_resources

from lizard_fewsunblobbed.models import Timeserie
from lizard_map import coordinates
from lizard_map.adapter import Graph
from lizard_map.daterange import current_start_end_dates
from lizard_map.daterange import DateRangeForm
from lizard_map.models import Workspace
from lizard_waterbalance.compute import WaterbalanceComputer2
from lizard_waterbalance.concentration_computer import ConcentrationComputer
from lizard_waterbalance.management.commands.compute_waterbalance import create_waterbalance_computer
#from lizard_waterbalance.forms import WaterbalanceAreaEditForm
from lizard_waterbalance.forms import WaterbalanceConfEditForm
from lizard_waterbalance.forms import OpenWaterEditForm
from lizard_waterbalance.forms import PumpingStationEditForm
from lizard_waterbalance.forms import create_location_label
from lizard_waterbalance.models import Concentration
from lizard_waterbalance.models import PumpingStation
from lizard_waterbalance.models import WaterbalanceArea
from lizard_waterbalance.models import WaterbalanceConf
from lizard_waterbalance.models import WaterbalanceLabel
from lizard_waterbalance.models import WaterbalanceTimeserie
from timeseries.timeseriesstub import TimeseriesStub
from timeseries.timeseriesstub import grouped_event_values
from timeseries.timeseriesstub import multiply_timeseries

import hotshot
import os

try:
    import settings
    PROFILE_LOG_BASE = settings.PROFILE_LOG_BASE
except:
    PROFILE_LOG_BASE = "/tmp"


date2datetime = lambda d: datetime.datetime(d.year, d.month, d.day)


def profile(log_file):
    """Profile some callable.

    This decorator uses the hotshot profiler to profile some callable (like
    a view function or method) and dumps the profile data somewhere sensible
    for later processing and examination.

    It takes one argument, the profile log name. If it's a relative path, it
    places it under the PROFILE_LOG_BASE. It also inserts a time stamp into the
    file name, such that 'my_view.prof' become 'my_view-20100211T170321.prof',
    where the time stamp is in UTC. This makes it easy to run and compare
    multiple trials.
    """

    if not os.path.isabs(log_file):
        log_file = os.path.join(PROFILE_LOG_BASE, log_file)

    def _outer(f):
        def _inner(*args, **kwargs):
            # Add a timestamp to the profile output when the callable
            # is actually called.
            (base, ext) = os.path.splitext(log_file)
            base = base + "-" + time.strftime("%Y%m%dT%H%M%S", time.gmtime())
            final_log_file = base + ext

            prof = hotshot.Profile(final_log_file)
            try:
                ret = prof.runcall(f, *args, **kwargs)
            finally:
                prof.close()
            return ret

        return _inner
    return _outer

# We use the following values to uniquely identify the workspaces for
# 1. the general home page and
# 2. the waterbalance overview page.
# To make sure these values, which are primary keys, do not accidently
# identify a dynamically generated workspace, we have to define the
# two workspaces in the database in advance.
WATERBALANCE_HOMEPAGE_KEY = 2
WATERBALANCE_HOMEPAGE_NAME = "Waterbalance homepage"
CRUMB_HOMEPAGE = {'name': 'home', 'url': '/'}
GRAPH_TYPES = (
    ('waterbalans', u'Waterbalans'),
    ('waterpeil', u'Waterpeil'),
    ('waterpeil_met_sluitfout', u'Waterpeil met sluitfout'),
    ('cumulatief_debiet', u'Cumulatief debiet'),
    ('fracties_chloride', u'Fracties Chloride'),
    ('fracties_fosfaat', u'Fracties Fosfaat'),
    ('fosfaatbelasting', u'Fosfaatbelasting'),
)
IMPLEMENTED_GRAPH_TYPES = (
    'waterbalans',
    'waterpeil',
    'waterpeil_met_sluitfout',
    'fracties_chloride',
    'fracties_fosfaat',
    'fosfaatbelasting',
    )
BAR_WIDTH = {'year': 364,
             'quarter': 90,
             'month': 30,
             'day': 1}
# Exceptions for boolean fields: used in tab edit forms.
# Key is the field name, value is text used for (True, False).
TRUE_FALSE_EXCEPTIONS = {
    'computed_level_control': ('Berekend', 'Opgedrukt'),
    }

logger = logging.getLogger(__name__)


def waterbalance_graph_data(
    conf,
    start_datetime, end_datetime, recalculate=False):

    """Return the outcome needed for drawing the waterbalance graphs.

    Result is a compute.WaterbalanceOutcome object.

    """
    cache_key = '%s_%s_%s' % (conf, start_datetime, end_datetime)
    t1 = time.time()
    result = cache.get(cache_key)
    if (result is None) or recalculate:
        fews_data_filename = pkg_resources.resource_filename(
            "lizard_waterbalance", "testdata/timeserie.csv")
        waterbalance_area, waterbalance_computer = create_waterbalance_computer(
            conf, start_datetime, end_datetime, fews_data_filename)
        # waterbalance_computer = WaterbalanceComputer(store_timeserie=lambda m, n, t: None)
        # waterbalance_area = WaterbalanceConf.objects.get(slug=area)
        bucket2outcome, level_control, outcome = waterbalance_computer.compute(
            waterbalance_area, start_datetime, end_datetime)
        result = outcome
        cache.set(cache_key, result, 8 * 60 * 60)
        logger.debug("Stored waterbalance graph data in cache for %s", cache_key)
    else:
        logger.debug("Got waterbalance graph data from cache")
    t2 = time.time()
    logger.debug("Grabbing waterbalance data took %s seconds.", t2 - t1)
    return result


class TopHeight:
    """Maintains the height of the top of each bar in a stacked bar chart.

    Instance variable:
    * key_to_height -- dictionary that maps each bar to its total height

    Each bar is identified by a key, which often is its horizontal position in
    the chart. Let key be such anidentifier, then key_to_height[key] specifies
    the total height of the bar.

    """
    def __init__(self):
        self.key_to_height = {}

    def stack_bars(self, keys, heights):
        """Sets or update the heights for the given bars.

        Parameters:
        * keys -- list of bar keys
        * heights -- list of additional bar heights

        """
        for key, height in zip(keys, heights):
            self.key_to_height.setdefault(key, 0)
            self.key_to_height[key] += height

    def get_heights(self, keys):
        """Return the list of heights for the given bars.

        Parameters:
        * keys -- list of bar keys

        When a specified key is not present, this method returns 0 for that
        key.

        """
        heights = []
        for key in keys:
            heights.append(self.key_to_height.get(key, 0))

        return heights


def indicator_graph(request,
                    area=None,
                    id=None):
    class MockTimeserie(object):
        class MockTimeSerieData(object):
            def all(self):
                return []
        name = 'geen tijdreeks beschikbaar'
        timeseriedata = MockTimeSerieData()


def waterbalance_start(
    request,
    template='lizard_waterbalance/waterbalance-overview.html',
    crumbs_prepend=None):
    """Show waterbalance overview workspace.

    The workspace for the waterbalance homepage should already be present.

    Parameters:
    * crumbs_prepend -- list of breadcrumbs

    """
    if crumbs_prepend is None:
        crumbs = [{'name': 'home', 'url': '/'}]
    else:
        crumbs = list(crumbs_prepend)
    crumbs.append({'name': 'Waterbalans overzicht',
                   'title': 'Waterbalans overzicht',
                   'url': reverse('waterbalance_start')})

    special_homepage_workspace = \
        get_object_or_404(Workspace, pk=WATERBALANCE_HOMEPAGE_KEY)
    return render_to_response(
        template,
        {'waterbalance_configurations': WaterbalanceConf.objects.all(),
         'workspaces': {'user': [special_homepage_workspace]},
         'javascript_hover_handler': 'popup_hover_handler',
         'javascript_click_handler': 'waterbalance_area_click_handler',
         'crumbs': crumbs},
        context_instance=RequestContext(request))


def waterbalance_area_summary(
    request,
    area_slug,
    scenario_slug,
    template='lizard_waterbalance/waterbalance_area_summary.html',
    crumbs_prepend=None):
    """Show the summary page of the named WaterbalanceArea.

    Parameters:
    * area -- slug of the WaterbalanceArea whose summary has to be shown
    * scenario -- slug of the WaterbalanceScenario
    * crumbs_prepend -- list of breadcrumbs

    """
    # waterbalance_configuration = get_object_or_404(
    #     WaterbalanceConf,
    #     waterbalance_area__slug=area,
    #     waterbalance_scenario__slug=scenario)
    #logger.debug('%s - %s' % (area, scenario))
    waterbalance_configuration = WaterbalanceConf.objects.get(
        waterbalance_area__slug=area_slug,
        waterbalance_scenario__slug=scenario_slug)

    area = waterbalance_configuration.waterbalance_area

    date_range_form = DateRangeForm(
        current_start_end_dates(request, for_form=True))

    if crumbs_prepend is None:
        crumbs = [{'name': 'home', 'url': '/'}]
    else:
        crumbs = list(crumbs_prepend)
    crumbs.append({'name': 'Waterbalans overzicht',
                   'title': 'Waterbalans overzicht',
                   'url': reverse('waterbalance_start')})

    kwargs = {'area_slug': area_slug, 'scenario_slug': scenario_slug}
    crumbs.append({'name': area.name,
                   'title': area.name,
                   'url': reverse('waterbalance_area_summary', kwargs=kwargs)})

    graph_type_formitems = []
    for index, (graph_type, name) in enumerate(GRAPH_TYPES):
        formitem = {}
        formitem['id'] = 'id_graph_type_%s' % index
        formitem['value'] = graph_type
        formitem['label'] = name
        formitem['disabled'] = (graph_type not in IMPLEMENTED_GRAPH_TYPES)
        graph_type_formitems.append(formitem)
    periods = [('year', 'Per jaar', False),
               ('month', 'Per maand', True),
               ('quarter', 'Per kwartaal', False),
               ('day', 'Per dag', False)]
    # ^^^ True/False: whether it is the default radio button.  So month is.

    return render_to_response(
        template,
        {'waterbalance_configuration': waterbalance_configuration,
         'date_range_form': date_range_form,
         'graph_type_formitems': graph_type_formitems,
         'periods': periods,
         'crumbs': crumbs},
        context_instance=RequestContext(request))


def get_timeseries(timeseries, start, end, period='month'):
    """Return the events for the given timeseries in the given range.

    Parameters:
    * timeseries -- implementation of a time series that supports a method events()
    * start -- the earliest date (and/or time) of a returned event
    * end -- the latest date (and/or time) of a returned event
    * period -- 'year', 'month' or 'day'

    """
    return zip(*(e for e in grouped_event_values(timeseries, period)
                 if e[0] >= start and e[0] < end))


def get_average_timeseries(timeseries, start, end, period='month'):
    """Return the events for the given timeseries in the given range.

    Parameters:
    * timeseries -- implementation of a time series that supports a method events()
    * start -- the earliest date (and/or time) of a returned event
    * end -- the latest date (and/or time) of a returned event
    * period -- 'year', 'month' or 'day'

    """
    return zip(*(e for e in grouped_event_values(timeseries, period, average=True)
                 if e[0] >= start and e[0] < end))


def get_timeseries_label(name):
    """Return the WaterbalanceLabel wth the given name.

    If no such label exists, we log the fact that nu such label exists and return
    a dummy label.

    """
    try:
        label = WaterbalanceLabel.objects.get(name__iexact=name)
    except WaterbalanceLabel.DoesNotExist:
        logger.warning("Unable to retrieve the WaterbalanceLabel '%s'", name)
        label = WaterbalanceLabel()
        label.color = "000000"
    return label


def retrieve_horizon(request):
    """Return the start and end datetime.datetime on the horizontal axis.

    The user selects the start and end date but not the date and time. This method returns
    the start date at 00:00 and the end date at 23:59:59.

    """
    start_date, end_date = current_start_end_dates(request)
    start_datetime = datetime.datetime(start_date.year,
                                       start_date.month,
                                       start_date.day,
                                       0,
                                       0,
                                       0)
    end_datetime = datetime.datetime(end_date.year,
                                     end_date.month,
                                     end_date.day,
                                     23,
                                     59,
                                     59)
    return start_datetime, end_datetime


# @profile("waterbalance_area_graph.prof")
def waterbalance_area_graph(
    conf,
    period,
    start_date, end_date,
    start_datetime, end_datetime,
    width, height):
    """Draw the graph for the given area and of the given type.

    area_slug: i.e. artsveldsche-polder-oost
    period: i.e. 'month'
    start_date, end_date: start and end_date for graph
    start_datetime, end_datetime: start and enddate for calculation
    width, height: width and height of output image
    """

    graph = Graph(start_date, end_date, width, height)

    graph.suptitle("Waterbalans [m3]")

    bar_width = BAR_WIDTH[period]

    wb_computer = WaterbalanceComputer2(conf)

    incoming = wb_computer.get_open_water_incoming_flows(
        start_datetime, end_datetime)
    incoming_bars = [("verhard", incoming["hardened"]),
                     ("gedraineerd", incoming["drained"]),
                     ("afstroming", incoming["flow_off"]),
                     ("uitspoeling", incoming["undrained"]),
                     ("neerslag", incoming["precipitation"]),
                     ("kwel", incoming["seepage"])]
    incoming_bars += [
        (structure.name, timeserie) for structure, timeserie in
        incoming['defined_input'].items()]
    incoming_bars.append(
        ("peilhandhaving inlaat", incoming["computed_intake"]))

    t1 = time.time()

    outgoing = wb_computer.get_open_water_outgoing_flows(start_datetime, end_datetime)

    outgoing_bars = [
        ("intrek", outgoing["indraft"]),
        ("verdamping", outgoing["evaporation"]),
        ("wegzijging", outgoing["infiltration"]),
         ]

    outgoing_bars += [(structure.name, timeserie) for structure, timeserie in outgoing['defined_output'].items()]
    outgoing_bars.append(("peilhandhaving uitlaat", outgoing["computed_pumps"]))

    names = [bar[0] for bar in incoming_bars + outgoing_bars]
    colors = ['#' + get_timeseries_label(name).color for name in names]
    handles = [Line2D([], [], color=color, lw=4) for color in colors]

    graph.legend_space()
    graph.legend(handles, names)

    for bars in [incoming_bars, outgoing_bars]:
        top_height = TopHeight()
        for bar in bars:
            label = get_timeseries_label(bar[0])
            times, values = get_timeseries(bar[1], start_datetime, end_datetime,
                                           period=period)

            # add the following keyword argument to give the bar edges the same
            # color as the bar itself: edgecolor='#' + label.color

            color = '#' + label.color
            bottom = top_height.get_heights(times)
            graph.axes.bar(times, values, bar_width, color=color, edgecolor=color,
                               bottom=bottom)
            top_height.stack_bars(times, values)

    t2 = time.time()
    logger.debug("Grabbing all graph data took %s seconds.", t2 - t1)

    canvas = FigureCanvas(graph.figure)
    response = HttpResponse(content_type='image/png')
    canvas.print_png(response)
    return response


def waterbalance_sluice_error(
    area_slug, scenario_slug, start_date, end_date, width, height):
    """Draw sluice error.
    """
    # Get/calculate timeseries
    configuration = WaterbalanceConf.objects.get(
        waterbalance_area__slug=area_slug,
        waterbalance_scenario__slug=scenario_slug)
    waterbalance_computer = WaterbalanceComputer2(configuration)

    # Enforces that data is calculated between start_date and end_date
    ts = waterbalance_computer.get_sluice_error_timeseries(
        date2datetime(start_date), date2datetime(end_date),
        # start_date, end_date,
        timestep=WaterbalanceTimeserie.TIMESTEP_DAY)

    # Draw this timeseries
    graph = Graph(start_date, end_date, width, height)

    # Normally we would just fetch times and values
    # times, values = ts.times_values(start_date, end_date)
    # We have to display the cumulative value per year
    times = []
    values = []
    current_value = 0
    previous_dt = None
    for event in ts.get_timeseries().timeseries_events.filter(
        time__gte=start_date, time__lte=end_date):

        if previous_dt is None or previous_dt.year != event.time.year:
            current_value = 0

        current_value += event.value
        previous_dt = event.time
        times.append(event.time)
        values.append(current_value)

    color = '#0000ff'
    graph.axes.plot(times, values, color=color)

    graph.add_today()

    # Return response
    canvas = FigureCanvas(graph.figure)
    response = HttpResponse(content_type='image/png')
    canvas.print_png(response)
    return response


def waterbalance_water_level(request,
                             area=None,
                             graph_type=None):
    """Draw the graph for the given area and of the given type."""

    period = request.GET.get('period', 'month')
    start_datetime, end_datetime = retrieve_horizon(request)
    start_date = start_datetime.date()
    end_date = end_datetime.date() + datetime.timedelta(1)

    width = request.GET.get('width', 1600)
    height = request.GET.get('height', 400)
    krw_graph = Graph(start_date, end_date, width, height)

    title = "Waterpeil "
    if graph_type == "waterpeil_met_sluitfout":
        title += "met sluitfout "
    krw_graph.suptitle(title + "[m NAP]")

    outcome = waterbalance_graph_data(area, start_datetime, end_datetime)

    waterbalance_configuration = WaterbalanceConf.objects.get(slug=area)

    t1 = time.time()

    bars = [
        #("waterpeil gemeten", waterbalance_configuration.water_level),
        ("waterpeil berekend", outcome.open_water_timeseries["water level"]),
        ]

    # Add sluice error to bars.
    if graph_type == "waterpeil_met_sluitfout":
        sluice_error = TimeseriesStub()
        previous_year = None
        # We have computed the sluice error in [m3/day], however we
        # will display it as a difference in water level, so
        # [m/day]. We make that translation here.
        for event in outcome.open_water_timeseries["sluice error"].events():
            date = event[0]
            if previous_year is None or previous_year < date.year:
                value = 0
                previous_year = date.year
            value += (1.0 * event[1]) / waterbalance_configuration.open_water.surface
            sluice_error.add_value(date, value)
        bars.append(("sluitfout", sluice_error))

    names = [bar[0] for bar in bars]
    colors = ['#' + get_timeseries_label(name).color for name in names]
    handles = [Line2D([], [], color=color, lw=4) for color in colors]

    krw_graph.legend_space()
    krw_graph.legend(handles, names)

    for bar in bars:
        label_name = bar[0]
        label = get_timeseries_label(label_name)
        try:
            times, values = get_average_timeseries(
                bar[1], start_datetime,
                end_datetime, period=period)
        except:
            logger.warning("Unable to retrieve the time series for '%s'", label_name)
            continue
        color = '#' + label.color
        krw_graph.axes.plot(times, values, color=color)

    t2 = time.time()
    logger.debug("Grabbing all graph data took %s seconds.", t2 - t1)

    canvas = FigureCanvas(krw_graph.figure)
    response = HttpResponse(content_type='image/png')
    canvas.print_png(response)
    return response


def fraction_distribution(
    conf, period, start_date, end_date, width, height):
    """
    Draw graph for given configuration for chloride or phosphate.

    UNFINISHED.
    """
    # Fetch needed data
    wb_computer = WaterbalanceComputer2(conf)
    wb_timeseries = wb_computer.get_input_timeseries(start_date, end_date)

    substance = Concentration.SUBSTANCE_CHLORIDE
    title = "Fractieverdeling xxx"

    # We need in this order on axis 1: berging, neerslag, kwel, verhard,
    # gedraineerd, ongedraineerd, afstroming, <intakes with
    # computed_level_control=False>, <intakes with
    # computed_level_control=True>

    # Axis 2: Computed substance levels, measured substance levels in
    # present.


    # Draw graph
    graph = Graph(start_date, end_date, width, height)
    ax2 = graph.axes.twinx()
    graph.suptitle(title)

    canvas = FigureCanvas(graph.figure)
    response = HttpResponse(content_type='image/png')
    canvas.print_png(response)
    return response


#@profile("waterbalance_fraction_distribution.prof")
def waterbalance_fraction_distribution(
    name, conf, graph_type, period,
    start_date, end_date, start_datetime, end_datetime,
    width, height):
    """Draw the graph for the given area and of the given type."""

    graph = Graph(start_date, end_date, width, height)
    ax2 = graph.axes.twinx()

    if graph_type == 'fracties_chloride':
        substance = Concentration.SUBSTANCE_CHLORIDE
    else:
        substance = Concentration.SUBSTANCE_PHOSPHATE

    title = "Fractieverdeling "
    if substance == Concentration.SUBSTANCE_CHLORIDE:
        title += "chloride"
    else:
        title += "fosfaat"
    graph.suptitle(title)

    bar_width = BAR_WIDTH[period]

    wb_computer = WaterbalanceComputer2(conf)
    wb_timeseries = wb_computer.get_fraction_timeseries(
        start_datetime, end_datetime)

    t1 = time.time()

    # (Temp) removed concentrations from bar[2]. 'neerslag', 'kwel',
    # 'verhard', 'gedraineerd', 'ongedraineerd', 'afstroming'

    # conf.concentrations.get(
    #     substance__exact=substance,
    #     flow_name__iexact='neerslag').minimum),

    bars = [("berging", wb_timeseries["initial"]),
            ("neerslag", wb_timeseries["precipitation"]),
            ("kwel", wb_timeseries["seepage"]),
            ("verhard", wb_timeseries["hardened"]),
            ("gedraineerd", wb_timeseries["drained"]),
            ("ongedraineerd", wb_timeseries["undrained"]),
            ("afstroming", wb_timeseries["flow_off"]),
            ]

    intakes = PumpingStation.objects.filter(
        into=True, computed_level_control=False)
    # Temp removed
    # conf.concentrations.get(
    #        substance__exact=substance,
    #        flow_name__iexact=intake.name).minimum)
    for intake in intakes.order_by('name'):
        bars.append(
            (intake.name,
             # outcome.intake_fractions[intake],
             wb_timeseries['intakes'][intake]))

    names = [bar[0] for bar in bars]
    if substance == Concentration.SUBSTANCE_CHLORIDE:
        names.append("chloride")
    else:
        names.append("fosfaat")

    colors = ['#' + get_timeseries_label(name).color for name in names]
    handles = [Line2D([], [], color=color, lw=4) for color in colors]

    # we add the legend entries for the measured substance levels

    substance_color = colors[-1]
    handles.append(Line2D([], [], linestyle=' ',color=substance_color, marker='D'))
    substance_name = names[-1]
    names.append(substance_name + " meting")

    graph.legend_space()
    graph.legend(handles, names)

    # Now draw the graph
    times = []
    values = []
    top_height = TopHeight()
    for bar in bars:

        label = get_timeseries_label(bar[0])
        times, values = get_average_timeseries(
            bar[1], start_datetime, end_datetime,
            period=period)

        # add the following keyword argument to give the bar edges the same
        # color as the bar itself: edgecolor='#' + label.color

        color = '#' + label.color
        bottom = top_height.get_heights(times)
        graph.axes.bar(times, values, bar_width, color=color, edgecolor=color,
                       bottom=bottom)
        top_height.stack_bars(times, values)

    # Skipping berging/initial??
    # fractions_list = [bar[1] for bar in bars[1:]]  # TimeseriesStubs
    #concentrations = [bar[2] for bar in bars[1:]]  # minimum concentrations

    # Draw axis 2
    # show the computed substance levels
    # substance_timeseries = ConcentrationComputer().compute(
    #     fractions_list,
    #     outcome.open_water_timeseries["storage"],
    #     concentrations)
    # times, values = get_average_timeseries(
    #     substance_timeseries, start_datetime, end_datetime,
    #     period=period)

    # ax2.plot(times, values, 'k-')

    # show the measured substance levels when they are present
    # try:
    #     if substance == Concentration.SUBSTANCE_CHLORIDE:
    #         substance_timeseries = conf.chloride
    #     else:
    #         substance_timeseries = conf.phosphate
    #     times, values = get_average_timeseries(substance_timeseries,
    #                                            start_datetime,
    #                                            end_datetime,
    #                                            period=period)
    #     ax2.plot(times, values, 'k-')
    # except AttributeError:
    #     logger.warning("Unable to retrieve measured time series for %s",
    #                    substance_name)

    t2 = time.time()

    logger.debug("Grabbing all graph data took %s seconds.", t2 - t1)

    graph.add_today()

    canvas = FigureCanvas(graph.figure)
    response = HttpResponse(content_type='image/png')
    canvas.print_png(response)
    return response


def waterbalance_phosphate_impact(
    name, conf, period, start_date, end_date, start_datetime, end_datetime,
    width, height):
    """Draw the graph for the given area and of the given type."""

    graph = Graph(start_date, end_date, width, height)

    graph.suptitle("Fosfaatbelasting [mg/m2]")

    bar_width = BAR_WIDTH[period]
    stopwatch_start = datetime.datetime.now()
    # logger.debug('Started waterbalance_phosphate_impact at %s' %
    #              stopwatch_start)

    # wb_computer = WaterbalanceComputer2(conf)
    # wb_timeseries = wb_computer.

    outcome = waterbalance_graph_data(conf, start_datetime, end_datetime)

    phosphate = Concentration.SUBSTANCE_PHOSPHATE

    # One bar is (name incr, name min, discharge, increment value,
    # minimum value)
    bar_contents = [
        ('precipitation', 'neerslag'), ('seepage', 'kwel'),
        ('hardened', 'verhard'), ('drained', 'gedraineerd'),
        ('undrained', 'ongedraineerd'), ('flow_off', 'afstroming'),]

    bars = [('%s (incr)' % name_dutch,
             '%s (min)' % name_dutch,
             outcome.open_water_timeseries[name],
             conf.concentrations.get(
                substance__exact=phosphate,
                flow_name__iexact=name_dutch).increment,
             conf.concentrations.get(
                substance__exact=phosphate,
                flow_name__iexact=name_dutch).minimum)
            for name, name_dutch in bar_contents]

    logger.debug('1: Got bars %s' %
                 (datetime.datetime.now() - stopwatch_start))

    # Add intakes to bars
    intakes = PumpingStation.objects.filter(
        into=True, computed_level_control=False)
    for intake in intakes.order_by('name'):
        bars.append(
            (intake.name + " (incr)",
             intake.name + " (min)",
             intake.retrieve_sum_timeseries(),
             conf.concentrations.get(
                    substance__exact=phosphate,
                    flow_name__iexact=intake.name).increment,
             conf.concentrations.get(
                    substance__exact=phosphate,
                    flow_name__iexact=intake.name).minimum))

    intakes = PumpingStation.objects.filter(
        into=True, computed_level_control=True)
    for intake in intakes.order_by('name'):
        bars.append(
            (intake.name + " (incr)",
             intake.name + " (min)",
             outcome.level_control_assignment[intake],
             conf.concentrations.get(
                    substance__exact=phosphate,
                    flow_name__iexact=intake.name).increment,
             conf.concentrations.get(
                    substance__exact=phosphate,
                    flow_name__iexact=intake.name).minimum))

    logger.debug('2: Got intakes %s' %
                 (datetime.datetime.now() - stopwatch_start))

    names = [bar[0] for bar in bars] + [bar[1] for bar in bars]
    colors = ['#' + get_timeseries_label(name).color for name in names]
    handles = [Line2D([], [], color=color, lw=4) for color in colors]

    graph.legend_space()
    graph.legend(handles, names)

    open_water = conf.open_water

    top_height = TopHeight()

    for index in range(2):
        # if index == 0, we are talking about the minimum values,
        # if index == 1, we are talking about the incremental values
        for bar in bars:
            # Label is the min name or the incr name
            label = get_timeseries_label(bar[1-index])
            discharge = bar[2]

            if index == 0:
                # Minimum value
                concentration = bar[4]
            else:
                # Maximum value = Incremental value + Minimum value
                concentration = bar[3] + bar[4]
            # Concentration is specified in [mg/l] whereas discharge is
            # specified in [m3/day]. The impact is specified in [mg/m2/day] so
            # we first multiply the concentration by 1000 to specify it in
            # [mg/m3] and then divide the result by the surface of the open
            # water to specify it in [mg/m2/m3].
            concentration = (concentration * 1000.0) / open_water.surface

            impact_timeseries = multiply_timeseries(discharge, concentration)

            times, values = get_average_timeseries(impact_timeseries, start_datetime, end_datetime,
                                                   period=period)

            # add the following keyword argument to give the bar edges the same
            # color as the bar itself: edgecolor='#' + label.color

            color = '#' + label.color
            bottom = top_height.get_heights(times)
            graph.axes.bar(
                times, values, bar_width, color=color, edgecolor=color,
                bottom=bottom)
            top_height.stack_bars(times, values)

    logger.debug('3: Got axes %s' %
                 (datetime.datetime.now() - stopwatch_start))

    canvas = FigureCanvas(graph.figure)
    response = HttpResponse(content_type='image/png')
    canvas.print_png(response)

    logger.debug('4: Got response %s' %
                 (datetime.datetime.now() - stopwatch_start))
    return response


def waterbalance_area_graphs(request,
                             area_slug,
                             scenario_slug,
                             graph_type=None):
    """
    Return area graph.

    Fetch request parameters: name, period, width, height.
    """
    name = request.GET.get('name', "landelijk")
    conf = WaterbalanceConf.objects.get(
        waterbalance_area__slug=area_slug,
        waterbalance_scenario__slug=scenario_slug)

    period = request.GET.get('period', 'month')
    start_datetime, end_datetime = retrieve_horizon(request)
    start_date = start_datetime.date()
    end_date = end_datetime.date() + datetime.timedelta(1)

    # Don't know the difference in above start/end dates. This seems
    # better, but not sure if it works correctly with existing
    # functions.
    _start_date, _end_date = current_start_end_dates(request)

    width = request.GET.get('width', 1600)
    height = request.GET.get('height', 400)

    if graph_type == 'waterbalans':
        return waterbalance_area_graph(
            conf, period, start_date, end_date, start_datetime,
            end_datetime, width, height)
    elif graph_type == 'waterpeil' or graph_type == 'waterpeil_met_sluitfout':
        # return waterbalance_water_level(request, area, graph_type)
        return waterbalance_sluice_error(
            area_slug, scenario_slug, _start_date, _end_date, width, height)
    elif graph_type == 'fracties_chloride' or graph_type == 'fracties_fosfaat':
        return waterbalance_fraction_distribution(
            name, conf, graph_type, period, start_date, end_date,
            start_datetime, end_datetime,
            width, height)
        # return fraction_distribution(
        #     conf, period, start_date, end_date, width, height)
    elif graph_type == 'fosfaatbelasting':
        return waterbalance_phosphate_impact(
            name, conf, period, start_date, end_date,
            start_datetime, end_datetime, width, height)


def waterbalance_shapefile_search(request):
    """Return url to redirect to if a waterbody is found.
    """
    google_x = float(request.GET.get('x'))
    google_y = float(request.GET.get('y'))

    # Set up a basic map as only map can search...
    mapnik_map = mapnik.Map(400, 400)
    mapnik_map.srs = coordinates.GOOGLE

    workspace = Workspace.objects.get(name=WATERBALANCE_HOMEPAGE_NAME)
    first_workspace_item = workspace.workspace_items.all()[0]
    adapter = first_workspace_item.adapter

    search_results = adapter.search(google_x, google_y)
    # Return url of first found object.
    for search_result in search_results:
        id_in_shapefile = search_result['identifier']['id']
        waterbalance_area = \
            WaterbalanceArea.objects.get(name=id_in_shapefile)
        return HttpResponse(waterbalance_area.get_absolute_url())

    # Nothing found? Return an empty response and the javascript popup handler
    # will fire.
    return HttpResponse('')


def graph_select(request):
    """
    Processes ajax call, return appropriate png urls.
    """

    graphs = []
    if request.is_ajax():
        area_slug = request.POST['area_slug']
        scenario_slug = request.POST['scenario_slug']
        selected_graph_types = request.POST.getlist('graphs')
        period = request.POST['period']

        for graph_type, name in GRAPH_TYPES:
            if not graph_type in selected_graph_types:
                continue

            url = (reverse('waterbalance_area_graph',
                           kwargs={'area_slug': area_slug,
                                   'scenario_slug': scenario_slug,
                                   'graph_type': graph_type}) +
                   '?period=' + period)
            graphs.append(url)
        json = simplejson.dumps(graphs)
        return HttpResponse(json, mimetype='application/json')
    else:
        return HttpResponse("Should not be run this way.")


def search_fews_lkeys(request):
    if request.is_ajax():
        pkey = request.POST['pkey']
        fkey = request.POST['fkey']
        timeseries = Timeserie.objects.filter(parameterkey=pkey, filterkey=fkey)
        timeseries = timeseries.distinct().order_by("locationkey")
        lkeys = [(ts.locationkey.lkey, create_location_label(ts.locationkey)) for ts in timeseries]
        json = simplejson.dumps(lkeys)
        return HttpResponse(json, mimetype='application/json')
    else:
        return HttpResponse("Should not be run this way.")


def _actual_recalculation(request, area_slug, scenario_slug):
    """Recalculate graph data by emptying the cache: used by two views."""
    start_datetime, end_datetime = retrieve_horizon(request)

    conf = WaterbalanceConf.objects.get(
        waterbalance_area__slug=area_slug,
        waterbalance_scenario__slug=scenario_slug)

    waterbalance_graph_data(conf, start_datetime, end_datetime,
                            recalculate=True)


def recalculate_graph_data(request, area_slug=None, scenario_slug=None):
    """Recalculate the graph data by emptying the cache."""
    if request.method == "POST":
        _actual_recalculation(request, area_slug, scenario_slug)
        return HttpResponseRedirect(
            reverse(
                'waterbalance_area_summary',
                kwargs={'area_slug': area_slug,
                        'scenario_slug': scenario_slug}))
    else:
        return HttpResponse("false")


def waterbalance_area_edit(request,
                           area_slug=None,
                           template='lizard_waterbalance/waterbalance_area_edit.html',
                           crumbs_prepend=None):
    """Show the edit page of the named WaterbalanceArea.

    Injected with ajax into the waterbalance_area_summary page.

    Parameters:
    * area -- name of the WaterbalanceArea whose summary has to be shown
    * crumbs_prepend -- list of breadcrumbs

    """
    return render_to_response(
        template,
        {'area': area_slug,
         },
        context_instance=RequestContext(request))


def _sub_multiple(request,
                  instances=None,
                  template=None,
                  field_names=None,
                  header_name=None,
                  form_class=None,
                  form_url=None):
    """
    Generic sub multiple screen (?)

    instance is a model object
    """
    if template is None:
        template = 'lizard_waterbalance/waterbalance_area_edit_multiple.html'
    header = []
    lines = []
    if instances:
        instance = instances[0]
        header_item = {}
        header_item['name'] = instance._meta.get_field(header_name).verbose_name.capitalize()
        header.append(header_item)
        for field_name in field_names:
            line = {}
            field = instance._meta.get_field(field_name)
            row_header = {}
            row_header['name'] = field.verbose_name.capitalize()
            row_header['title'] = field.help_text
            line['header'] = row_header
            line['items'] = []
            lines.append(line)

    for instance in instances:
        header_item = {}
        header_item['name'] = getattr(instance, header_name).capitalize()
        if form_url:
            header_item['edit_url'] = form_url + str(instance.id) + '/'
        header.append(header_item)
        for index, field_name in enumerate(field_names):
            line = lines[index]
            item = {}
            item['value'] = getattr(instance, field_name)
            if field_name in TRUE_FALSE_EXCEPTIONS:
                if isinstance(item['value'], bool):
                    if item['value']:
                        item['value'] = TRUE_FALSE_EXCEPTIONS[field_name][0]
                    else:
                        item['value'] = TRUE_FALSE_EXCEPTIONS[field_name][1]
            line['items'].append(item)


    return render_to_response(
        template,
        {'header': header,
         'lines': lines,
         },
        context_instance=RequestContext(request))


def _sub_edit(request,
              area_slug,
              scenario_slug,
              instance=None,
              template=None,
              fixed_field_names=None,
              form_class=None,
              form_url=None,
              previous_url=None):
    """
    Generic sub edit screen (?)
    """
    if template is None:
        template = 'lizard_waterbalance/waterbalance_area_edit_sub.html'
    fixed_items = []
    for fixed_field_name in fixed_field_names:
        field = instance._meta.get_field(fixed_field_name)
        fixed_items.append(dict(
                name=field.verbose_name.capitalize(),
                title=field.help_text,
                value=getattr(instance, fixed_field_name)))
    form = None
    if form_class is not None:
        if request.method == 'POST':
            form = form_class(request.POST, instance=instance)
            if form.is_valid():
                form.save()
                _actual_recalculation(request, area_slug, scenario_slug)
                messages.success(
                    request,
                    u"Gegevens zijn opgeslagen en de grafiek is herberekend.")
        else:
            form = form_class(instance=instance)

    return render_to_response(
        template,
        {'fixed_items': fixed_items,
         'form': form,
         'form_url': form_url,
         'previous_url': previous_url,
         },
        context_instance=RequestContext(request))


def waterbalance_area_edit_sub_conf(request,
                                    area_slug,
                                    scenario_slug,
                                    template=None):
    instance = get_object_or_404(
        WaterbalanceConf,
        waterbalance_area__slug=area_slug,
        waterbalance_scenario__slug=scenario_slug)
    fixed_field_names = []  # ['name']
    form_class = WaterbalanceConfEditForm
    form_url = reverse('waterbalance_area_edit_sub_conf',
                       kwargs={'area': area_slug, 'scenario': scenario_slug})
    return _sub_edit(request,
                     area_slug=area_slug,
                     scenario_slug=scenario_slug,
                     instance=instance,
                     template=template,
                     fixed_field_names=fixed_field_names,
                     form_class=form_class,
                     form_url=form_url,
                     )


def waterbalance_area_edit_sub_openwater(request,
                                         area_slug,
                                         scenario_slug,
                                         template=None):
    conf = get_object_or_404(
        WaterbalanceConf,
        waterbalance_area__slug=area_slug,
        waterbalance_scenario__slug=scenario_slug)
    instance = conf.open_water
    fixed_field_names = ['name']
    form_class = OpenWaterEditForm
    form_url = reverse(
        'waterbalance_area_edit_sub_openwater',
        kwargs={'area_slug': area_slug, 'scenario_slug': scenario_slug})
    return _sub_edit(request,
                     area_slug=area_slug,
                     scenario_slug=scenario_slug,
                     instance=instance,
                     template=template,
                     fixed_field_names=fixed_field_names,
                     form_class=form_class,
                     form_url=form_url,
                     )

def waterbalance_area_edit_sub_buckets(request,
                                       area_slug,
                                       scenario_slug,
                                       template=None):
    conf = get_object_or_404(
        WaterbalanceConf,
        waterbalance_area__slug=area_slug,
        waterbalance_scenario__slug=scenario_slug)
    instance = conf.open_water
    fixed_field_names = []
    return _sub_edit(request,
                     area_slug=area_slug,
                     scenario_slug=scenario_slug,
                     instance=instance,
                     template=template,
                     fixed_field_names=fixed_field_names,
                     )


def waterbalance_area_edit_sub_out(request,
                                   area_slug,
                                   scenario_slug,
                                   template=None):
    """Posten uit."""
    conf = get_object_or_404(
        WaterbalanceConf,
        waterbalance_area__slug=area_slug,
        waterbalance_scenario__slug=scenario_slug)
    instances = [ps for ps in conf.open_water.pumping_stations.all()
                 if not ps.into]

    header_name = 'name'
    field_names = ['percentage',
                   'computed_level_control',
                   ]
    return _sub_multiple(request,
                         instances=instances,
                         template=template,
                         field_names=field_names,
                         header_name=header_name,
                         )


def waterbalance_area_edit_sub_in(request,
                                  area_slug,
                                  scenario_slug,
                                  template=None):
    conf = get_object_or_404(
        WaterbalanceConf,
        waterbalance_area__slug=area_slug,
        waterbalance_scenario__slug=scenario_slug)
    instances = [ps for ps in conf.open_water.pumping_stations.all()
                 if ps.into]

    header_name = 'name'
    field_names = ['percentage',
                   'computed_level_control',
                   ]
    form_url = reverse(
        'waterbalance_area_edit_sub_in',
        kwargs={'area_slug': area_slug, 'scenario_slug': scenario_slug})

    return _sub_multiple(request,
                         instances=instances,
                         template=template,
                         field_names=field_names,
                         header_name=header_name,
                         form_url=form_url,
                         )


def waterbalance_area_edit_sub_in_single(request,
                                         area_slug,
                                         scenario_slug,
                                         pump_id,
                                         template=None):
    instance = get_object_or_404(PumpingStation, pk=int(pump_id))
    fixed_field_names = []
    form_class = PumpingStationEditForm
    form_url = reverse(
        'waterbalance_area_edit_sub_in_single',
        kwargs={'area_slug': area_slug,
                'scenario_slug': scenario_slug,
                'pump_id': pump_id})
    previous_url = reverse(
        'waterbalance_area_edit_sub_in',
        kwargs={'area_slug': area_slug, 'scenario_slug': scenario_slug})
    return _sub_edit(request,
                     area_slug=area_slug,
                     scenario_slug=scenario_slug,
                     instance=instance,
                     template=template,
                     fixed_field_names=fixed_field_names,
                     form_class=form_class,
                     form_url=form_url,
                     previous_url=previous_url,
                     )


def waterbalance_area_edit_sub_labels(request,
                                      area_slug,
                                      scenario_slug,
                                      template=None):
    conf = get_object_or_404(
        WaterbalanceConf,
        waterbalance_area__slug=area_slug,
        waterbalance_scenario__slug=scenario_slug)
    instance = conf.open_water
    fixed_field_names = []
    return _sub_edit(request,
                     area_slug=area_slug,
                     scenario_slug=scenario_slug,
                     instance=instance,
                     template=template,
                     fixed_field_names=fixed_field_names,
                     )


def waterbalance_area_edit_sub7(request,
                                area_slug,
                                scenario_slug,
                                template=None):
    conf = get_object_or_404(
        WaterbalanceConf,
        waterbalance_area__slug=area_slug,
        waterbalance_scenario__slug=scenario_slug)
    instance = conf.open_water
    fixed_field_names = []
    return _sub_edit(request,
                     area=area_slug,
                     scenario_slug=scenario_slug,
                     instance=instance,
                     template=template,
                     fixed_field_names=fixed_field_names,
                     )
