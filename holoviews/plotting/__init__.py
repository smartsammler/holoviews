import os
from io import BytesIO
from tempfile import NamedTemporaryFile
from hashlib import sha256

import param

from ..core.options import Cycle, Options, Store,  SaveOptions, save_options
from ..core import Layout, NdLayout, GridSpace
from .annotation import * # pyflakes:ignore (API import)
from .chart import * # pyflakes:ignore (API import)
from .chart3d import * # pyflakes:ignore (API import)
from .plot import * # pyflakes:ignore (API import)
from .raster import * # pyflakes:ignore (API import)
from .tabular import * # pyflakes:ignore (API import)
from . import pandas # pyflakes:ignore (API import)
from . import seaborn # pyflakes:ignore (API import)


# Tags used when matplotlib output is to be embedded in HTML
GIF_TAG = "<center><img src='data:image/gif;base64,{b64}' style='max-width:100%'/><center/>"
VIDEO_TAG = """
<center><video controls style='max-width:100%'>
<source src="data:video/{mime_type};base64,{b64}" type="video/{mime_type}">
Your browser does not support the video tag.
</video><center/>"""


# <format name> : (animation writer, mime_type,  anim_kwargs, extra_args, tag)
ANIMATION_OPTS = {
    'webm': ('ffmpeg', 'webm', {},
             ['-vcodec', 'libvpx', '-b', '1000k'],
             VIDEO_TAG),
    'h264': ('ffmpeg', 'mp4', {'codec': 'libx264'},
             ['-pix_fmt', 'yuv420p'],
             VIDEO_TAG),
    'gif': ('imagemagick', 'gif', {'fps': 10}, [],
            GIF_TAG),
    'scrubber': ('html', None, {'fps': 5}, None, None)
}



class Export(object):
    """
    Collection of class methods used for rendering data from
    matplotlib, either to a stream or directly to file.
    """

    obj = None
    SHA = None     # For testing purposes: the output SHA.
    SHA_mode = 0   # 0: No SHA, 1: SHA (file not saved), 2: SHA (file saved)


    @classmethod
    def save_fig(cls, figure, fmt, basename=None, dpi=72, auto=True):
        filename ='%s.%s' % (basename, fmt) if basename else None
        if not filename and auto:
            filename = save_options.filename(cls.obj, fmt)
        if filename is None: return

        figure_data = cls.figure_data(figure, fmt, dpi=dpi)
        if cls.digest(figure_data) == 1: return
        with open(filename, 'w') as f:
            f.write(figure_data)

    @classmethod
    def save_anim(cls, anim, fmt, writer, basename=None, dpi=72, auto=True, **anim_kwargs):
        filename ='%s.%s' % (basename, fmt) if basename else None
        if not filename and auto:
            filename = save_options.filename(cls.obj, fmt)
        if filename is None: return
        if cls.SHA_mode == 0:
            anim.save(filename, writer=writer, dpi=dpi, **anim_kwargs)
        else:
            anim_data = cls.anim_data(anim, fmt, writer, dpi, **anim_kwargs)
            if cls.digest(anim_data) == 1: return
            with open(filename, 'w') as f:
                f.write(anim_data)

    @classmethod
    def anim_data(cls, anim, fmt, writer, dpi, **anim_kwargs):
        """
        Render an animation and return the resulting data.
        """
        if not hasattr(anim, '_encoded_video'):
            with NamedTemporaryFile(suffix='.%s' % fmt) as f:
                anim.save(f.name, writer=writer, dpi=dpi, **anim_kwargs)
                video = open(f.name, "rb").read()
        return video


    @classmethod
    def figure_data(cls, fig, fmt='png', bbox_inches='tight', **kwargs):
        """
        Render figure to image and return the resulting data.

        Similar to IPython.core.pylabtools.print_figure but without
        requiring IPython.
        """
        from matplotlib import rcParams
        kw = dict(
            format=fmt,
            facecolor=fig.get_facecolor(),
            edgecolor=fig.get_edgecolor(),
            dpi=rcParams['savefig.dpi'],
            bbox_inches=bbox_inches,
        )
        kw.update(kwargs)

        bytes_io = BytesIO()
        fig.canvas.print_figure(bytes_io, **kw)
        data = bytes_io.getvalue()
        if fmt == 'svg':
            data = data.decode('utf-8')
        return data


    @classmethod
    def digest(cls, data):
        """
        Sets the SHA hexdigest for the data to cls.SHA and returns the
        SHA_mode.
        """
        if cls.SHA_mode != 0:
            hashfn = sha256()
            hashfn.update(data)
            cls.SHA  = hashfn.hexdigest()
        else:
            cls.SHA = None
        return cls.SHA_mode



def opts(el, size):
    "Returns the plot options with supplied size (if not overridden)"
    return dict(figure_size=size, **Store.lookup_options(el, 'plot').options)

def get_plot_size(obj, percent_size):
    """
    Given a holoviews object and a percentage size, apply heuristics
    to compute a suitable figure size. For instance, scaling layouts
    and grids linearly can result in unwieldy figure sizes when there
    are a large number of elements. As ad hoc heuristics are used,
    this functionality is kept separate from the plotting classes
    themselves.

    Used by the IPython Notebook display hooks and the save
    utility. Note that this can be overridden explicitly per object
    using the figure_size and size plot options.
    """
    def rescale_figure(percent_size):
        factor = percent_size / 100.0
        return (Plot.figure_size[0] * factor,
                Plot.figure_size[1] * factor)

    if isinstance(obj, (Layout, NdLayout)):
        return (obj.shape[1]*rescale_figure(percent_size)[1],
                obj.shape[0]*rescale_figure(percent_size)[0])
    elif isinstance(obj, GridSpace):
        max_dim = max(obj.shape)
        # Reduce plot size as GridSpace gets larger
        shape_factor = 1. / max_dim
        # Expand small grids to a sensible viewing size
        expand_factor = 1 + (max_dim - 1) * 0.1
        scale_factor = expand_factor * shape_factor
        return (scale_factor * obj.shape[0] * rescale_figure(percent_size)[0],
                scale_factor * obj.shape[1] * rescale_figure(percent_size)[1])
    else:
        return rescale_figure(percent_size)


def save(obj, basename=None, fmt=None,
         fig_default='svg', holomap_default='gif',
         size=100, dpi=72, fps=20, save_options=save_options):
    """
    Save a HoloViews object to file, either to image format (png or
    svg) or animation format (webm, h264, gif).

    Both basename and the format may be explicitly specified,
    otherwise they will be autogenerated using the supplied
    save_options object and defaults respectively. In particular, the
    file format will be specified as fig_default argument for static
    figures and will be the holomap_default argument for holomaps with
    multiple keys.

    Note that the default save_options argument correspond to the
    global object of the same name. This object has the timestamp set
    when HoloViews is first imported into the active session.

    The remaining options are size (specified as a percentage), dpi
    (resolution in dots per inch) and the fps (frames per second)
    option for animated formats.
    """
    animation_formats = ['webm','h264', 'gif']
    figure_formats = ['png', 'svg']
    formats = animation_formats + figure_formats

    if not isinstance(save_options, SaveOptions):
        raise Exception("The save_options argument must be an instance of SaveOptions.")

    if isinstance(obj, AdjointLayout):
        obj = Layout.from_values(obj)
    try:
        plotclass = Store.defaults[type(obj)]
    except KeyError:
        raise Exception("No corresponding plot type found for %r" % type(obj))

    plot = plotclass(obj, **opts(obj,  get_plot_size(obj, size)))

    if fmt is None:
        fmt = holomap_default if len(plot) > 1 else fig_default
    if fmt not in formats:
        raise ValueError("File format must be one of %s" % ','.join(formats))

    if basename is not None:
        filename = '%s.%s' % (basename, fmt)
    elif save_options is None:
        raise Exception("No filename can be selected as no basename "
                        "supplied and no SaveOptions instance specified.")
    else:
        filename = save_options.filename(obj, fmt)

    if fmt in animation_formats:
        (writer, mime_type, anim_kwargs, extra_args, tag) = ANIMATION_OPTS[fmt]
        anim_kwargs = dict(anim_kwargs, **({'fps':fps} if fmt =='gif' else {}))
        anim = plot.anim(fps)
        if extra_args != []:
            anim_kwargs = dict(anim_kwargs, extra_args=extra_args)
        anim.save(filename, writer=writer, dpi=dpi, **anim_kwargs)
    else:
        fig = plot()
        kw = dict(
            format=fmt, dpi=dpi,
            facecolor=fig.get_facecolor(),
            edgecolor=fig.get_edgecolor())
        with open(filename, 'w') as f:
            fig.canvas.print_figure(f, **kw)


Store.register_plots()

# Charts
Store.options.Curve = Options('style', color=Cycle(), linewidth=2)
Store.options.Scatter = Options('style', color=Cycle(), marker='o')
Store.options.Bars = Options('style', ec='k', fc=Cycle())
Store.options.Histogram = Options('style', ec='k', fc=Cycle())
Store.options.Points = Options('style', color=Cycle(), marker='o')
Store.options.Scatter3D = Options('style', color=Cycle(), marker='o')
# Rasters
Store.options.Image = Options('style', cmap='hot', interpolation='nearest')
Store.options.Raster = Options('style', cmap='hot', interpolation='nearest')
Store.options.HeatMap = Options('style', cmap='RdYlBu_r', interpolation='nearest')
Store.options.HeatMap = Options('plot', show_values=True, xticks=20, yticks=20)
Store.options.RGBA = Options('style', interpolation='nearest')
Store.options.RGB = Options('style', interpolation='nearest')
# Composites
Store.options.GridSpace = Options('style', **{'font.size': 10, 'axes.labelsize': 'small',
                                              'axes.titlesize': 'small'})
# Annotations
Store.options.VLine = Options('style', color=Cycle())
Store.options.HLine = Options('style', color=Cycle())
Store.options.Spline = Options('style', lw=2)
Store.options.Text = Options('style', fontsize=13)
Store.options.Arrow = Options('style', color='k', lw=2, fontsize=13)
# Paths
Store.options.Contours = Options('style', color=Cycle())
Store.options.Path = Options('style', color=Cycle())
Store.options.Box = Options('style', color=Cycle())
Store.options.Bounds = Options('style', color=Cycle())
Store.options.Ellipse = Options('style', color=Cycle())
# Interface
Store.options.TimeSeries = Options('style', color=Cycle())


from ..core import Dimension
from matplotlib.ticker import FormatStrFormatter
Dimension.type_formatters[int] = FormatStrFormatter("%d")
Dimension.type_formatters[float] = FormatStrFormatter("%.3g")
Dimension.type_formatters[np.float32] = FormatStrFormatter("%.3g")
Dimension.type_formatters[np.float64] = FormatStrFormatter("%.3g")

# Defining the most common style options for HoloViews
GrayNearest = Options(key='style', cmap='gray', interpolation='nearest')

def public(obj):
    if not isinstance(obj, type): return False
    baseclasses = [Plot]
    return any([issubclass(obj, bc) for bc in baseclasses])


_public = ["PlotSaver", "GrayNearest"] + list(set([_k for _k, _v in locals().items() if public(_v)]))
__all__ = _public
