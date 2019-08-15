# =============================================================================
# Copyright (C) 2010 Diego Duclos
#
# This file is part of pyfa.
#
# pyfa is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# pyfa is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with pyfa.  If not, see <http://www.gnu.org/licenses/>.
# =============================================================================


import itertools
import os
import traceback


# noinspection PyPackageRequirements
import wx
from logbook import Logger


from graphs.style import BASE_COLORS, LIGHTNESSES, STYLES, hsl_to_hsv


pyfalog = Logger(__name__)


try:
    import matplotlib as mpl

    mpl_version = int(mpl.__version__[0]) or -1
    if mpl_version >= 2:
        mpl.use('wxagg')
        graphFrame_enabled = True
    else:
        graphFrame_enabled = False

    from matplotlib.lines import Line2D
    from matplotlib.backends.backend_wxagg import FigureCanvasWxAgg as Canvas
    from matplotlib.figure import Figure
    from matplotlib.colors import hsv_to_rgb
except ImportError as e:
    pyfalog.warning('Matplotlib failed to import.  Likely missing or incompatible version.')
    graphFrame_enabled = False
except Exception:
    # We can get exceptions deep within matplotlib. Catch those.  See GH #1046
    tb = traceback.format_exc()
    pyfalog.critical('Exception when importing Matplotlib. Continuing without importing.')
    pyfalog.critical(tb)
    graphFrame_enabled = False


class GraphCanvasPanel(wx.Panel):

    def __init__(self, graphFrame, parent):
        super().__init__(parent)
        self.graphFrame = graphFrame

        # Remove matplotlib font cache, see #234
        try:
            cache_dir = mpl._get_cachedir()
        except:
            cache_dir = os.path.expanduser(os.path.join('~', '.matplotlib'))
        cache_file = os.path.join(cache_dir, 'fontList.cache')
        if os.access(cache_dir, os.W_OK | os.X_OK) and os.path.isfile(cache_file):
            os.remove(cache_file)

        mainSizer = wx.BoxSizer(wx.VERTICAL)

        self.figure = Figure(figsize=(5, 3), tight_layout={'pad': 1.08})
        rgbtuple = wx.SystemSettings.GetColour(wx.SYS_COLOUR_BTNFACE).Get()
        clr = [c / 255. for c in rgbtuple]
        self.figure.set_facecolor(clr)
        self.figure.set_edgecolor(clr)
        self.canvas = Canvas(self, -1, self.figure)
        self.canvas.SetBackgroundColour(wx.Colour(*rgbtuple))
        self.canvas.mpl_connect('button_press_event', self.OnMplCanvasClick)
        self.subplot = self.figure.add_subplot(111)
        self.subplot.grid(True)
        mainSizer.Add(self.canvas, 1, wx.EXPAND | wx.ALL, 0)

        self.SetSizer(mainSizer)

        self.xMark = None
        self.mplOnDragHandler = None
        self.mplOnReleaseHandler = None

    def draw(self, accurateMarks=True):
        self.subplot.clear()
        self.subplot.grid(True)
        allXs = set()
        allYs = set()
        legendData = []
        chosenX = self.graphFrame.ctrlPanel.xType
        chosenY = self.graphFrame.ctrlPanel.yType
        self.subplot.set(xlabel=self.graphFrame.ctrlPanel.formatLabel(chosenX), ylabel=self.graphFrame.ctrlPanel.formatLabel(chosenY))

        mainInput, miscInputs = self.graphFrame.ctrlPanel.getValues()
        view = self.graphFrame.getView()
        sources = self.graphFrame.ctrlPanel.sources
        if view.hasTargets:
            iterList = tuple(itertools.product(sources, self.graphFrame.ctrlPanel.targets))
        else:
            iterList = tuple((f, None) for f in sources)

        # Draw plot lines and get data for legend
        for source, target in iterList:
            # Get line style data
            try:
                colorData = BASE_COLORS[source.colorID]
            except KeyError:
                pyfalog.warning('Invalid color "{}" for "{}"'.format(source.colorID, source.name))
                continue
            color = colorData.hsl
            lineStyle = 'solid'
            if target is not None:
                try:
                    lightnessData = LIGHTNESSES[target.lightnessID]
                except KeyError:
                    pyfalog.warning('Invalid lightness "{}" for "{}"'.format(target.lightnessID, target.name))
                    continue
                color = lightnessData.func(color)
                try:
                    lineStyleData = STYLES[target.lineStyleID]
                except KeyError:
                    pyfalog.warning('Invalid line style "{}" for "{}"'.format(target.lightnessID, target.name))
                    continue
                lineStyle = lineStyleData.mplSpec
            color = hsv_to_rgb(hsl_to_hsv(color))

            # Get point data
            try:
                xs, ys = view.getPlotPoints(
                    mainInput=mainInput,
                    miscInputs=miscInputs,
                    xSpec=chosenX,
                    ySpec=chosenY,
                    src=source,
                    tgt=target)
                allXs.update(xs)
                allYs.update(ys)
                # If we have single data point, show marker - otherwise line won't be shown
                if len(xs) == 1 and len(ys) == 1:
                    self.subplot.plot(xs, ys, color=color, linestyle=lineStyle, marker='.')
                else:
                    self.subplot.plot(xs, ys, color=color, linestyle=lineStyle)
                # Fill data for legend
                if target is None:
                    legendData.append((color, lineStyle, source.shortName))
                else:
                    legendData.append((color, lineStyle, '{} vs {}'.format(source.shortName, target.shortName)))
            except Exception:
                pyfalog.warning('Invalid values in "{0}"', source.name)
                self.canvas.draw()
                self.Refresh()
                return

        # Setting Y limits for canvas
        if self.graphFrame.ctrlPanel.showY0:
            allYs.add(0)
        minY = min(allYs, default=0)
        maxY = max(allYs, default=0)
        # Extend range a little for some visual space
        yRange = maxY - minY
        minY -= yRange * 0.05
        maxY += yRange * 0.05
        # Extend by % of value if we show function of a constant
        if minY == maxY:
            minY -= minY * 0.05
            maxY += minY * 0.05
        # If still equal, function is 0, spread out visual space as special case
        if minY == maxY:
            minY -= 5
            maxY += 5
        self.subplot.set_ylim(bottom=minY, top=maxY)

        # Process X marks line
        if self.xMark is not None:
            minX = min(allXs, default=None)
            maxX = max(allXs, default=None)
            if minX is not None and maxX is not None:
                xMark = max(min(self.xMark, maxX), minX)
                self.subplot.axvline(x=xMark, linestyle='dotted', linewidth=1, color=(0, 0, 0))


        legendLines = []
        for i, iData in enumerate(legendData):
            color, lineStyle, label = iData
            legendLines.append(Line2D([0], [0], color=color, linestyle=lineStyle, label=label.replace('$', '\$')))

        if len(legendLines) > 0 and self.graphFrame.ctrlPanel.showLegend:
            legend = self.subplot.legend(handles=legendLines)
            for t in legend.get_texts():
                t.set_fontsize('small')
            for l in legend.get_lines():
                l.set_linewidth(1)

        self.canvas.draw()
        self.Refresh()

    def markXApproximate(self, x):
        if x is not None:
            self.xMark = x
            self.draw(accurateMarks=False)

    def markXAccurate(self, x):
        if x is not None:
            self.xMark = x
            self.draw()

    def unmarkX(self):
        self.xMark = None
        self.draw()

    # Matplotlib event handlers
    def OnMplCanvasClick(self, event):
        if event.button == 1:
            if not self.mplOnDragHandler:
                self.mplOnDragHandler = self.canvas.mpl_connect('motion_notify_event', self.OnMplCanvasDrag)
            if not self.mplOnReleaseHandler:
                self.mplOnReleaseHandler = self.canvas.mpl_connect('button_release_event', self.OnMplCanvasRelease)
            self.markXApproximate(event.xdata)
        elif event.button == 3:
            self.unmarkX()

    def OnMplCanvasDrag(self, event):
        self.markXApproximate(event.xdata)

    def OnMplCanvasRelease(self, event):
        if event.button == 1:
            if self.mplOnDragHandler:
                self.canvas.mpl_disconnect(self.mplOnDragHandler)
                self.mplOnDragHandler = None
            if self.mplOnReleaseHandler:
                self.canvas.mpl_disconnect(self.mplOnReleaseHandler)
                self.mplOnReleaseHandler = None
            self.markXAccurate(event.xdata)