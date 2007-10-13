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

from StringIO import StringIO

import pygame, urllib, threading, random, sqlite3

#PROXIES = {'http': 'http://fastweb.bell.ca:8083/'}
PROXIES = {}
DB_PATH = '/media/mmc1/gmaps.db'

class TileCache:
    def __init__(self):
        # tile returned when there is no cached data
        self.blackTile = pygame.Surface((256, 256))
        
        self.server = TileServer(self)
        self.server.setDaemon(True)
        self.server.start()
        
        # decoding the png files is expensive, keep a fixed size cache
        self.lock = threading.Lock() # synchronizes cache
        
        self.cacheInserts = 0
        self.items = {}
        self.lru = []
        self.maxSize = 20
        
    def shutdown(self):
        self.server.shutdown()
        self.server.join()
        
    def fetchTile(self, uid):
        # make sure the tile is within bounds
        # zoom 17 = 1 tile, zoom 16 = 2 tiles, zoom 15 = 4 tiles, etc
        
        x, y, zoom = uid
        
        maxTile = (1 << (17 - zoom)) - 1
        if x < 0 or y < 0 or x > maxTile or y > maxTile:
            return self.blackTile
        
        # try the cache
        
        self.lock.acquire()
        
        if self.items.has_key(uid):
            surface = self.items[uid]
            
            # in case we have a placeholder item, return the blackTile
            if surface == None:
                surface = self.blackTile
            
            self.lru.remove(uid)
        else:
            surface = self.blackTile
            
            # request async data from the database
            self.server.requestData(uid)
            
            # placeholder data till the asyc request returns
            self.items[uid] = None
            
        self.lru.append(uid)
        
        if len(self.lru) > self.maxSize:
            old = self.lru.pop(0)
            del(self.items[old])
        
        self.lock.release()
        
        return surface
        
    def getTiles(self, uidList):
        
        surfaceList = []
        
        for uid in uidList:
            surface = self.fetchTile(uid)
            surfaceList.append(surface)
        
        return surfaceList
        
    def putData(self, uid, data):
        self.lock.acquire()
        
        # figure out if this data is still fresh; sometimes async requests
        # take too long to come back, so the data we insert is 'obsolete'
        obsolete = not self.items.has_key(uid)
        
        self.lock.release()
        
        if obsolete: return
        
        if len(data) > 0:
            fh = StringIO(data)
            surface = pygame.image.load(fh, 'mt.png')
            fh.close()
        else:
            surface = self.blackTile
        
        self.lock.acquire()
        
        # the tile might have become obsolete while we were loading
        if self.items.has_key(uid):
            self.items[uid] = surface
            self.cacheInserts += 1
        
        self.lock.release()
        
    def hasTiles(self):
        self.lock.acquire()
        
        hasTiles = self.cacheInserts > 0
        self.cacheInserts = 0
        
        self.lock.release()
        
        return hasTiles
        
class TileServer(threading.Thread):
    def __init__(self, parent):
        threading.Thread.__init__(self)
        
        self.parent = parent
        
        self.insertCount = 0 # used to know when to commit
        self.maxInserts = 40 # after how many inserts do we commit
        
        # define and start the worker threads, these are used to download tiles
        self.maxWorkers = 2
        self.nextWorker = 0 # worker who gets the next request
        
        self.workers = []
        for n in range(self.maxWorkers):
            worker = Worker(self)
            worker.setDaemon(True)
            worker.start()
            
            self.workers.append(worker)
        
        # define the "buckets" used for async requests 
        self.lock = threading.Condition()
        
        self.requests = [] # incoming from TileServer
        self.pending = [] # outgoing to Worker
        
        self.results = {} # incoming from Worker
        
        self.done = False
        
    def __putData(self, uid, data):
        x, y, zoom = uid
        params = (x, y, zoom, data)
        
        self.db.execute('INSERT INTO tiles VALUES(?, ?, ?, ?)', params)
        
        self.insertCount = (self.insertCount + 1) % self.maxInserts
        if self.insertCount == 0:
            self.db.commit()
        
    def __getData(self, uid):
        cur = self.db.execute(
            """
            SELECT data
            FROM tiles
            WHERE
                x = ?
                AND y = ?
                AND zoom = ?
            """, uid)
        result = cur.fetchone()
        cur.close()
        
        if result:
            data = result[0]
        else:
            data = None
            
        return data
        
    def run(self):
        
        # define the sqlite connection
        self.db = sqlite3.connect(DB_PATH)
        
        # create the data tables and indexes if it is not found
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS tiles (
                x INTEGER,
                y INTEGER,
                zoom INTEGER,
                data BLOB)
            """)
        
        self.db.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS tiles_index
            ON tiles (x, y, zoom)
            """)
        
        self.db.commit()
        
        self.done = False
        
        while not self.done:
            self.lock.acquire()
            
            if not self.requests and not self.results:
                self.lock.wait()
                
            requests = self.requests
            self.requests = []
            
            results = self.results
            self.results = {}
            
            self.lock.release()
            
            # store incoming data from Worker threads
            for uid, data in results.items():
                if data == None:
                    pass # TODO: retry the download
                else:
                    # if len(data) >= 0
                    self.__putData(uid, data)
                    self.parent.putData(uid, data)
                
                self.pending.remove(uid)
            
            # fetch data for requests from TileServer (database or url)
            for uid in requests:
                # make sure no async url request is pending for this item
                if uid not in self.pending:
                    data = self.__getData(uid)
                    
                    if data == None:
                        # start async url request
                        self.nextWorker = (self.nextWorker + 1) % self.maxWorkers
                        self.workers[self.nextWorker].requestData(uid)
                        
                        self.pending.append(uid)
                    else:
                        self.parent.putData(uid, data)
        
        self.db.commit()
        self.db.close()
        
    def shutdown(self):
        self.lock.acquire()
        
        self.done = True
        
        self.lock.notify()
        self.lock.release()
        
    def requestData(self, uid):
        self.lock.acquire()
        
        if uid not in self.requests:
            self.requests.append(uid)
        
        self.lock.notify()
        self.lock.release()
    
    def putData(self, uid, data):
        """Saves data into the database (async)
        
        if len(data) > 0
            good data
        elif len(data) == 0
            bad data (404)
        elif data == None
            error (timeout)
        """
        self.lock.acquire()
        
        self.results[uid] = data
        
        self.lock.notify()
        self.lock.release()
    
class Worker(threading.Thread):
    def __init__(self, parent):
        threading.Thread.__init__(self)
        
        self.parent = parent
        
        self.lock = threading.Condition() # manages self.requests
        self.requests = [] # used as a stack
    
    def run(self):
        while True:
            # wait for new requests to come from the TileServer
            self.lock.acquire()
            
            if not self.requests:
                self.lock.wait()
            
            uid = self.requests.pop()
            
            self.lock.release()
            
            url = "http://mt.google.com/mt?x=%s&y=%s&zoom=%s" % uid
            
            # fetch data for the request
            data = None
            try:
                urlh = urllib.urlopen(url, proxies=PROXIES)
                
                # google does not store tiles for all the zoom levels
                # sometimes they will send a soft 404 text/html page
                
                if urlh.headers.type == 'image/png':
                    data = buffer(urlh.read())
                else:
                    data = ''
                    
                urlh.close()
            except:
                print 'Could not download %s' % url
                
            # send the data back to the TileServer
            self.parent.putData(uid, data)
            
    def requestData(self, uid):
        self.lock.acquire()
        
        self.requests.append(uid)
        
        self.lock.notify()
        self.lock.release()
        
