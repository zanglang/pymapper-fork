#!/usr/bin/env python

#Copyright 2007 Razvan Taranu
#
#This file is part of PyMapper.
#
#PyMapper is free software: you can redistribute it and/or modify
#it under the terms of the GNU General Public License as published by
#the Free Software Foundation, either version 3 of the License, or
#(at your option) any later version.
#
#PyMapper is distributed in the hope that it will be useful,
#but WITHOUT ANY WARRANTY; without even the implied warranty of
#MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#GNU General Public License for more details.
#
#You should have received a copy of the GNU General Public License
#along with PyMapper.  If not, see <http://www.gnu.org/licenses/>.
#
#PyMapper uses code from maemo-mapper

import math, pygame, sys

from TileServer import TileCache

K_MIDDLE = 13

K_BACK = 27

K_UP = 273
K_DOWN = 274
K_RIGHT = 275
K_LEFT = 276

K_MENU = 285
K_HOME = 286

K_FULLSCREEN = 287
K_ZOOM_IN = 288
K_ZOOM_OUT = 289

"""
MAX_ZOOM defines the largest map zoom level we will download.
(MAX_ZOOM - 1) is the largest map zoom level that the user can zoom to.
"""
MAX_ZOOM = 16
MERCATOR_SPAN = -6.28318377773622
MERCATOR_TOP = 3.14159188886811
TILE_SIZE_PIXELS = 256
TILE_SIZE_P2 = 8
WORLD_SIZE_UNITS = 2 << (MAX_ZOOM + TILE_SIZE_P2)

def latlon2unit(lat, lon):
    unitx = (lon + 180.0) * (WORLD_SIZE_UNITS / 360.0) + 0.5
    tmp = math.sin(lat * (math.pi / 180.0))
    unity = 0.5 + (WORLD_SIZE_UNITS / MERCATOR_SPAN)
    unity *= math.log((1.0 + tmp) / (1.0 - tmp)) * 0.5 - MERCATOR_TOP
    
    return [int(unitx), int(unity)]
    
def unit2latlon(unitx, unity):
    lon = (unitx * (360.0 / WORLD_SIZE_UNITS)) - 180.0
    lat = (360.0 * (math.atan(math.exp((unity * (MERCATOR_SPAN / WORLD_SIZE_UNITS)) + MERCATOR_TOP)))) * (1.0 / math.pi) - 90.0
    
    return [lat, lon]
    
def panunits(zoom):
    return (2 << (5 + zoom))
    
def tile2unit(tile, zoom):
    return ((tile) << (8 + zoom))
    
def unit2tile(unit, zoom):
    return ((unit) >> (8 + zoom))
    
def pixel2unit(pixel, zoom):
    return ((pixel) << zoom)
    
def unit2pixel(unit, zoom):
    return ((unit) >> zoom)
    
def unit2tilepixel(unit, zoom):
    tile = ((unit) >> (8 + zoom))
    unit2 = ((tile) << (8 + zoom)) # units for the top left corner of the tile
    
    pixel = ((unit) >> zoom) # pixels for the real position
    pixel2 = ((unit2) >> zoom) # pixels for the top-left corner of the tile
    
    return (tile, (pixel - pixel2))
    
def maxtiles(zoom):
    pass
    
class PyMapper:
    
    def __init__(self):
        pygame.init()
        self.tileCache = TileCache()
        
        self.units = latlon2unit(45.547717, -73.55484) # position in google units
        self.zoom = 8 # current zoom level (0-16)
        
        self.window = pygame.display.set_mode((800, 480), pygame.FULLSCREEN) 
        self.clock = pygame.time.Clock()
        
    def shutdown(self):
        self.tileCache.shutdown()
        pygame.quit()
        sys.exit(0)
        
    def drawScreen(self):
        # coordinates of the center tile
        # our position in pixels on the center tile
        tilex, pixelx = unit2tilepixel(self.units[0], self.zoom)
        tiley, pixely = unit2tilepixel(self.units[1], self.zoom)
        
        screenSize = (800, 480)
        
        # need to cover the screen, number of tiles to surround the center tile with
        h = int(math.ceil(math.ceil((screenSize[0] / 256.0) / 2)))
        v = int(math.ceil(math.ceil((screenSize[1] / 256.0) / 2)))
        
        # clear the screen
        
        screen = pygame.display.get_surface()
        screen.fill((0,0,0))
        
        # compute list of all tiles we need and their position on the screen
        
        pos = [] # position of each tile on the screen in pixels
        tiles = [] # coordinates of each tile (x, y, zoom)
        
        for t in range(-v, v + 1):
            for s in range(-h, h + 1):
                
                tiles.append((tilex + s, tiley + t, self.zoom))
                
                posx = screenSize[0] / 2 - pixelx + s * 256
                posy = screenSize[1] / 2 - pixely + t * 256
                
                pos.append((posx, posy))
                
        # fetch the tiles from the tile server
        images = self.tileCache.getTiles(tiles)
        
        # draw the tiles to screen
        for i in range((h * 2 + 1) * (v * 2 + 1)):
            screen.blit(images.pop(), pos.pop())
            
        # draw our position on the screen
        pygame.draw.circle(screen, (255, 0, 0), (screenSize[0] / 2, screenSize[1] / 2), 2)
        
        # we're using double buffering
        pygame.display.flip()
        
    def doInput(self, events):
        for event in events:
            if event.type == pygame.QUIT:
                self.shutdown()
            
            elif event.type == pygame.KEYUP:
                
                if event.key == K_ZOOM_IN:
                    self.zoom -= 1
                elif event.key == K_ZOOM_OUT:
                    self.zoom += 1
                    
                elif event.key == K_LEFT:
                    self.units[0] -= panunits(self.zoom)
                elif event.key == K_RIGHT:
                    self.units[0] += panunits(self.zoom)
                elif event.key == K_UP:
                    self.units[1] -= panunits(self.zoom)
                elif event.key == K_DOWN:
                    self.units[1] += panunits(self.zoom)
                    
                elif event.key == K_BACK:
                    self.shutdown()
                
                
                self.zoom = min(MAX_ZOOM - 1, self.zoom)
                self.zoom = max(0, self.zoom)
                
                self.needsRefresh = True
            
            elif event.type == pygame.MOUSEMOTION:
                if event.buttons[0]:
                    dx = -pixel2unit(event.rel[0], self.zoom)
                    dy = -pixel2unit(event.rel[1], self.zoom)
                    
                    self.units = [self.units[0] + dx, self.units[1] + dy]
                    
                    self.needsRefresh = True
                    
    def run(self):
        self.needsRefresh = True
        
        while True:
            
            self.doInput(pygame.event.get())
            
            if self.tileCache.hasTiles():
                self.needsRefresh = True
            
            if self.needsRefresh:
                self.drawScreen()
                
            self.needsRefresh = False
            
            pygame.display.set_caption("%.1f fps" % self.clock.get_fps())
            self.clock.tick(20)
     
if __name__ == '__main__':
    mapper = PyMapper()
    mapper.run()
    
