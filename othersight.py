# Othersight.py
# A discord bot to track your location and constantly post it to a discord server
# Peak security
# Made by Vaughn Woerpel as a fun saturday project
from aiohttp import web
import discord 
import requests
import pytz
from datetime import datetime
from tzlocal import get_localzone
import pyproj
from discord import app_commands
from discord.ext import commands
# Grabs the information from the config file
from config import token, apikey, guild, channel


MY_GUILD = discord.Object(id=int(guild))

# Class to hold all of the location data and its various functions. This serves to make the other sections of the code make far more sense, as all of the data parsing can be in one easy spot as a single object.
class LocationData():
    def __init__(self, data):
        # Gets the data to parse
        data = data['locations']
        # Gets the most recent location, and also the last location
        recent = data[len(data)-1]
        
        # Grabs, shortens, and sets current coordinate
        coordinates = ((recent['geometry'])['coordinates'])
        self.coordinates = f"{str(round(coordinates[1], 6))}, {str(round(coordinates[0], 6))}"
        # Grabs, shortens, and sets previous coordinate
        lastcoord = data[len(data)-2]['geometry']['coordinates']
        self.previous_coordinates = f"{str(round(lastcoord[1], 6))}, {str(round(lastcoord[0], 6))}"

        # Grabs the heading using pyproj to determine heading based on last coordinate and current coordinate
        geodesic = pyproj.Geod(ellps='WGS84')
        a = self.coordinates.split(",")
        b = self.previous_coordinates.split(",")
        self.fwd_heading,self.rev_heading,self.distance = geodesic.inv(a[0], a[1], b[0], b[1])

        # Grabs the properties
        properties = recent['properties']

        # Sets the speed, if there is no speed then it sets to be stationary
        self.speed = properties['speed']
        if self.speed == 0:
            self.speed = "Stationary"
        
        # Gets the battery level and formats as a percentage
        battery_level = properties['battery_level']
        self.battery_level = "{:.0%}".format(battery_level)

        # Sets the altitude
        self.altitude = properties['altitude']

        # Getting the proper timestamp and converts it into the local time. This is a fucking pain in the ass I hate timestamps.
        timestamp = properties['timestamp'].replace('T', ' ').replace('Z','')
        dt_utc = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')
        dt_utc = dt_utc.replace(tzinfo=pytz.UTC)
        local_tz = get_localzone() 
        dt_local = dt_utc.astimezone(local_tz)
        format  = "%m/%d/%Y %H:%M:%S"
        self.timestamp = dt_local.strftime(format)

        # Setting wifi information
        if len(properties['wifi'])!= 0:
            self.wifi = properties['wifi']
        else:
            self.wifi = "None"

        # Gets the address of the location using a google maps API request
        base_url = "https://maps.googleapis.com/maps/api/geocode/json?"
        latlng = "latlng="+self.coordinates.replace(" ", "")
        key = "&key="+apikey
        response = requests.post(base_url+latlng+key)
        self.address = response.json()['results'][0]['formatted_address']

    # Generates a static google map image with a marker on my current location
    async def generate_static_map(self):
        base_url = "https://maps.googleapis.com/maps/api/staticmap?"
        base_url += "center="+self.coordinates.replace(" ", "")
        base_url += "&zoom=17&size=400x400&maptype=hybrid"
        base_url += "&markers=color:blue%7Clabel:V%7C"+self.coordinates.replace(" ", "")
        base_url += "&key="+apikey
        return base_url
    
    # Generates a static streetview based on my current location, and uses my heading to get where I'm *maybe* looking
    async def generate_static_streetview(self):
        base_url = "https://maps.googleapis.com/maps/api/streetview?"
        base_url += "size=400x400"
        base_url += "&location="+self.coordinates.replace(" ", "")
        base_url += "&fov=80&heading="+str(round(self.fwd_heading))
        base_url += "&pitch=0&key="+apikey
        return base_url
    
    # Generates the embed that gets sent in chat
    async def generate_embed(self):
        embed = discord.Embed(title="Tracker", color=0xe8921e)
        embed.add_field(name="Timestamp", value=self.timestamp, inline=True)
        embed.add_field(name="Coordinates", value=self.coordinates, inline=True)
        embed.add_field(name="Speed", value=self.speed, inline=True)
        embed.add_field(name="Altitude", value=self.altitude, inline=True)
        embed.add_field(name="Battery Level", value=self.battery_level, inline=True)
        embed.add_field(name="WiFi", value=self.wifi, inline=True)
        embed.add_field(name="Address", value=self.address, inline=True)
        return embed

    # Generates the view which controls the button
    async def generate_view(self):
        view = MapsView(self)
        return view

    # Simple printline for debugging location features
    def __str__(self):
        return f"--DATA--\nTimestamp: {self.timestamp}\nCoordinates: {self.coordinates}\nPrevious Coordinates: {self.previous_coordinates}\nForward Heading: {self.fwd_heading}\nSpeed: {self.speed}\nAltitude: {self.altitude}\nBattery Level: {self.battery_level}\nWiFi: {self.wifi}\nAddress: {self.address}"

# View setup for the buttons
class MapsView(discord.ui.View):
    def __init__(self, location):
        super().__init__()
        self.value = None
        self.location = location # Sets the view to have a location object so that previous maps can still be accessed while the program is running

    # UI button to get the static google map
    @discord.ui.button(label="Maps", style=discord.ButtonStyle.green)
    async def maps_button_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        url = await self.location.generate_static_map()
        await interaction.response.send_message(url)
    
    # UI button to get the static streetview
    @discord.ui.button(label="Street View", style=discord.ButtonStyle.green)
    async def streetview_button_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        url = await self.location.generate_static_streetview()
        await interaction.response.send_message(url)

# My discord bot client with all of the setuphook stuff so that the webserver doesn't bork itself
class MyClient(discord.Client):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.tree = app_commands.CommandTree(self)

    # Makes a setuphook background task so that the webserver runs
    async def setup_hook(self) -> None:
        self.bg_task = self.loop.create_task(self.webserver())
        self.tree.copy_global_to(guild=MY_GUILD)
        await self.tree.sync(guild=MY_GUILD)

    # Says it's ready and gets the channel and guild
    async def on_ready(self):
        print('Bot online!')
        print(guild)
        self.guild = self.get_guild(int(guild))
        self.channel = self.guild.get_channel(int(channel))
        print(f"Guild: {self.guild}")
        print(f"Channel: {self.channel}")

    # Webserver that handles all of the API requests
    async def webserver(self):
        async def api_handler(request):
            # Bad code practices occur in here 
            try:
                # Gets the POST request data json
                data = await request.json()
                # Turns post request json data into something meaningful with my bloated LocationData class __init__ method
                loc = LocationData(data)
                # Prints data to make sure it's working on the backend
                print(loc)
                # Generates embed, view, and sends the message
                embed = await loc.generate_embed()
                view = await loc.generate_view()
                await self.channel.send(embed=embed, view=view)
            except Exception as e:
                print("Error building data and sending message")
            # Sends response back to my phone to purge remaining data
            return web.json_response({"result":"ok"})

        # Creates a web app with a post endpoint
        app = web.Application()
        app.router.add_post('/endpoint', api_handler)
        runner = web.AppRunner(app)
        await runner.setup()
        self.site = web.TCPSite(runner, '0.0.0.0', 5000)
        await self.wait_until_ready()
        await self.site.start()

#Define Client
client = MyClient(intents=discord.Intents.default())

@client.tree.command()
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("Pong!")

# Runs the bot
client.run(token)
