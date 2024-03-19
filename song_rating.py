import csv
import requests
import webbrowser
from urllib.parse import urlencode, urlparse, parse_qs
import socketserver
import http.server
import os
import base64
import time

# Your application's credentials
client_id = 'client id goes here'
client_secret = 'client secreat goes here'
redirect_uri = 'http://localhost:8000'
scope = 'playlist-modify-public user-read-currently-playing'
playlist_ratings_folder = r'location for the playlist rating folder goes here (Must create a folder and put the path of it here'
song_updated = None

def setup():
    # Step 1: Construct the authorization URL
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scope
    }
    auth_url = "https://accounts.spotify.com/authorize?" + urlencode(params)

    # Open the URL in the user's browser
    webbrowser.open(auth_url)

    # Start a simple server to listen for the authorization code
    class Handler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'You can close this tab now.')

            # Extract the code from the URL
            code = parse_qs(urlparse(self.path).query).get('code')
            if code:
                # Save the code to a global variable
                global auth_code
                auth_code = code[0]

    # Start the server
    with socketserver.TCPServer(('localhost', 8000), Handler) as httpd:
        httpd.handle_request()

    # Step 2: Exchange the authorization code for an access token and refresh token
    token_url = 'https://accounts.spotify.com/api/token'
    token_data = {
        'grant_type': 'authorization_code',
        'code': auth_code,
        'redirect_uri': redirect_uri,
        'client_id': client_id,
        'client_secret': client_secret,
    }

    # Make the POST request
    response = requests.post(token_url, data=token_data)

    # Extract the access token and refresh token from the response
    token_json = response.json()
    access_token = token_json.get('access_token')
    refresh_token = token_json.get('refresh_token')
    return access_token, refresh_token

def get_refresh_token(refresh_token):
    auth_header = base64.b64encode(f"{client_id}:{client_secret}".encode('utf-8')).decode('utf-8')
    headers = {
        "Authorization": f"Basic {auth_header}"
    }
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token
    }
    response = requests.post("https://accounts.spotify.com/api/token", headers=headers, data=data)
    response_json = response.json()

    if response.status_code != 200:
        print(f"Failed to refresh token: {response.status_code}")
        print(response_json)
        return None, None
    expires_in = response_json.get("expires_in")
    expires_at = time.time() + expires_in
    return response_json.get("access_token"), expires_at

def check_playlist(access_token):
    # Get the current playback status
    playback_url = 'https://api.spotify.com/v1/me/player/currently-playing'
    headers = {
        'Authorization': 'Bearer ' + access_token
    }
    response = requests.get(playback_url, headers=headers)
    playback_json = response.json()

    # Check if the user is currently playing a song
    if playback_json.get('is_playing'):
        # Get the user's playlists
        playlists_url = 'https://api.spotify.com/v1/me/playlists'
        response = requests.get(playlists_url, headers=headers)
        playlists_json = response.json()
        if playlists_json.get('error'):
            print(playlists_json.get('error').get('message'))
            playlist_id = None
            playlist_name = None
            return playlist_id, playlist_name
        # Assuming 'playback_json' is the variable holding the currently playing track's information
        context = playback_json.get('context')
        if context is not None and context.get('type') == 'playlist':
            current_playlist_uri = context.get('uri')
            current_playlist_id = current_playlist_uri.split(':')[-1]
            
            # Now iterate over the playlists to find the matching one
            for playlist in playlists_json['items']:
                if playlist['id'] == current_playlist_id:
                    playlist_name = playlist['name']
                    playlist_id = playlist['id']
                    return playlist_id, playlist_name
    else:
        print("User is not currently listening to a song.")
        playlist_id = None
        playlist_name = None
        return playlist_id, playlist_name

def update_playlist_file(playlist_id, playlist_name, access_token):
    # Get the playlist songs
    headers = {
        'Authorization': 'Bearer ' + access_token
    }

    playlist_songs = []
    offset = 0
    while True:
        playlist_songs_url = f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks?offset={offset}"
        response = requests.get(playlist_songs_url, headers=headers)
        playlist_songs_json = response.json()

        # Extract the song names from the response
        playlist_songs.extend([track.get('track').get('name') for track in playlist_songs_json.get('items')])

        if playlist_songs_json.get('next'):
            offset += 100
        else:
            break
    # Check if the playlist ratings folder exists
    if not os.path.exists(playlist_ratings_folder):
        os.makedirs(playlist_ratings_folder)

    # Check if a file with the playlist name exists
    playlist_file_path = os.path.join(playlist_ratings_folder, f"{playlist_name}.csv")
    if os.path.exists(playlist_file_path):
        # Check if any songs in the playlist are not in the CSV file
        with open(playlist_file_path, 'r', encoding='utf-8') as file:
            reader = csv.reader(file)
            existing_songs = {row[0] for row in reader} # Use a set for faster lookups

        new_songs = set(playlist_songs) - existing_songs

        # Add new songs to the CSV file
        with open(playlist_file_path, 'a', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            for song in new_songs:
                writer.writerow([song, 0])

        # Check if any songs in the CSV file are not in the playlist
        with open(playlist_file_path, 'r', encoding='utf-8') as file:
            reader = csv.reader(file)
            csv_songs = {row[0] for row in reader}

        removed_songs = csv_songs - set(playlist_songs)

        # Remove songs from the CSV file
        if removed_songs:
            updated_rows = []
            with open(playlist_file_path, 'r', encoding='utf-8') as file:
                reader = csv.reader(file)
                for row in reader:
                    if row[0] not in removed_songs:
                        updated_rows.append(row)

            with open(playlist_file_path, 'w', newline='', encoding='utf-8') as file:
                writer = csv.writer(file)
                writer.writerow(['song name', 'rating']) # Add the header row
                writer.writerows(updated_rows)
    else:
        # Create a new file with the playlist name
        with open(playlist_file_path, 'w', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            writer.writerow(['song name', 'rating']) # Add the header row
            for song in playlist_songs:
                writer.writerow([song, 0])


def update_song_rating(song_name, playlist_id, playlist_name, increment):
    # Construct the file path for the playlist ratings
    playlist_file_path = os.path.join(playlist_ratings_folder, f"{playlist_name}.csv")

    # Check if the file exists
    if not os.path.exists(playlist_file_path):
        print(f"File {playlist_file_path} does not exist.")
        return

    # Read the existing data
    with open(playlist_file_path, 'r', newline='', encoding='utf-8') as file:
        reader = csv.reader(file)
        rows = list(reader)

    # Find the song and update its rating
    for i, row in enumerate(rows):
        if row[0] == song_name:
            # Increment the rating by the specified amount
            current_rating = int(row[1])
            new_rating = current_rating + increment
            rows[i][1] = str(new_rating)
            break

    # Write the updated data back to the file
    with open(playlist_file_path, 'w', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        writer.writerows(rows)

def reorganize_csv_by_rating(file_path):
    # Read the CSV file
    with open(file_path, 'r', newline='', encoding='utf-8') as csvfile:
        reader = csv.reader(csvfile)
        header = next(reader) # Skip the header row
        rows = list(reader)

    # Sort the rows based on the rating column (column 2) in descending order
    sorted_rows = sorted(rows, key=lambda row: int(row[1]), reverse=True)

    # Write the sorted rows back to the CSV file
    with open(file_path, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(header) # Write the header row
        writer.writerows(sorted_rows)

def song_ended_naturally_monitoring(access_token, playlist_id, playlist_name):
    global song_updated
    # Get the current playback status
    playback_url = 'https://api.spotify.com/v1/me/player/currently-playing'
    headers = {
        'Authorization': 'Bearer ' + access_token
    }
    response = requests.get(playback_url, headers=headers)
    playback_json = response.json()

    # Check if the user is currently playing a song
    if playback_json.get('is_playing'):
        # Get the current song's information
        song_name = playback_json.get('item').get('name')
        progress_ms = playback_json.get('progress_ms')
        duration_ms = playback_json.get('item').get('duration_ms')

        # Check if the song has finished playing or is within the last seconds
        if progress_ms >= duration_ms - 3000:
            # Update the rating for the song that ended naturally
            update_song_rating(song_name, playlist_id, playlist_name, 1)
            print(f"Updated rating for song '{song_name}'.")
            song_updated = True
    else:
        print("User is not currently playing a song.")

last_song = None
last_song_playing = False

def song_skipped_monitoring(access_token, playlist_id, playlist_name):
    global last_song, last_song_playing, song_updated
    if song_updated:
        return
    # Get the current playback status
    playback_url = 'https://api.spotify.com/v1/me/player/currently-playing'
    headers = {
        'Authorization': 'Bearer ' + access_token
    }
    response = requests.get(playback_url, headers=headers)
    playback_json = response.json()

    # Check if the user is currently playing a song
    if playback_json.get('is_playing'):
        current_song_name = playback_json.get('item').get('name')
        current_song_playing = True

        # If the current song is different from the last known song and the last song was playing,
        # it's likely a skip
        if last_song is not None and last_song != current_song_name and last_song_playing:
            # Update the rating for the last known song
            update_song_rating(last_song, playlist_id, playlist_name, 2)
            print(f"Updated rating for song '{last_song}' due to skip.")


        # Update the last song and its playback status
        last_song = current_song_name
        last_song_playing = current_song_playing

        # Return the current song name and its playback status
        return current_song_name, current_song_playing
    else:
        # If the user is not playing a song, return None for the current song name and False for its playback status
        last_song = None
        last_song_playing = False
        return None, False

# def reorder_playlist_by_csv(access_token, playlist_id, csv_file_path):
#     # Read the CSV file
#     with open(csv_file_path, 'r', encoding='utf-8') as file:
#         reader = csv.reader(file)
#         next(reader) # Skip the header row
#         songs = [row[0] for row in reader] # Assuming the first column contains song names
#         print('read csv')

#     # Function to search for a song and get its Spotify URI
#     def get_spotify_uri(song_name):
#         headers = {
#         'Authorization': 'Bearer ' + access_token
#     }
#         params = {'q': song_name, 'type': 'track', 'limit': 1}
#         try:
#             response = requests.get('https://api.spotify.com/v1/search', headers=headers, params=params)
#             if response.status_code == 200:
#                 track = response.json()['tracks']['items'][0]
#                 print(f"Got URI for song '{song_name}': {track['uri']}")
#                 return track['uri']
#             else:
#                 print(f"Failed to get URI for song '{song_name}': {response.status_code}")
#                 return None
#         except Exception as e:
#             print(f"Error getting URI for song '{song_name}': {e}")
#             return None

#     # Get Spotify URIs for all songs
#     uris = [get_spotify_uri(song) for song in songs]
#     print('got uris')

#     # Replace playlist tracks
#     headers = {
#         'Authorization': 'Bearer ' + access_token
#     }
#     data = {'uris': uris}
#     response = requests.put(f'https://api.spotify.com/v1/playlists/{playlist_id}/tracks', headers=headers, json=data)

#     if response.status_code == 201:
#         print("Playlist tracks replaced successfully.")
#     else:
#         print("Failed to replace playlist tracks.")

# Rest of the code...
access_token, refresh_token = setup()
access_token, expires_at = get_refresh_token(refresh_token)
while True:

    start_time = time.time()

    playlist_id, playlist_name = check_playlist(access_token)
    if playlist_id is not None and playlist_name is not None:
        update_playlist_file(playlist_id, playlist_name, access_token)
    # check if the access token has expired
    current_time = time.time()
    if current_time > expires_at:
        access_token, expires_at = get_refresh_token(refresh_token)

    # run monitoring functions
    song_ended_naturally_monitoring(access_token, playlist_id, playlist_name)
    song_skipped_monitoring(access_token, playlist_id, playlist_name)
    reorganize_csv_by_rating(os.path.join(playlist_ratings_folder, f"{playlist_name}.csv"))
    print('started reordering')
    # reorder_playlist_by_csv(access_token, playlist_id, (os.path.join(playlist_ratings_folder, f"{playlist_name}.csv")))



    execution_time = time.time() - start_time
    print('Loop finished in', execution_time, 'seconds.')
    if song_updated == True:
        last_song, last_song_playing = None, False
    song_updated = False
