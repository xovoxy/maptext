from flask import Flask, request, jsonify
import requests
from fontTools.ttLib import TTFont, TTLibError
from shapely.geometry import LineString
import numpy as np
import pdfkit
import os

app = Flask(__name__, static_folder='../public', static_url_path='/')

@app.route('/')
def index():
    return app.send_static_file('index.html')
AMAP_KEY = "e5bc839f31cd8c9d1a8ba3b8e9a595b4"  # Updated to match web API key

# Use an open-source font that supports Chinese characters
FONT_PATH = os.path.join(os.path.dirname(__file__), 'fonts', 'static', 'NotoSansSC-Regular.ttf')

def get_char_outline(text):
    font = TTFont(FONT_PATH)
    glyph = font.getGlyphSet()[font.getBestCmap()[ord(text[0])]]
    coords = []
    pen = type('Pen', (), {'moveTo': lambda self, pt: coords.append(pt), 'lineTo': lambda self, pt: coords.append(pt), 'closePath': lambda self: None})()
    glyph.draw(pen)
    return LineString(coords)

def scale_to_distance(outline, target_distance_km):
    current_length = outline.length
    scale = (target_distance_km * 1000) / current_length
    # Normalize coordinates to maintain aspect ratio
    coords = np.array(outline.coords)
    min_x, min_y = coords.min(axis=0)
    max_x, max_y = coords.max(axis=0)
    width = max_x - min_x
    height = max_y - min_y
    aspect_ratio = width / height if height != 0 else 1
    
    # Center the coordinates
    coords = coords - np.array([min_x + width/2, min_y + height/2])
    
    # Scale coordinates while maintaining aspect ratio
    scaled_coords = [(x * scale * aspect_ratio / 111000, y * scale / 111000) for x, y in coords]
    return scaled_coords

def get_bicycling_route(origin, waypoints, destination):
    url = "https://restapi.amap.com/v4/direction/bicycling"
    params = {
        "origin": f"{origin[0]},{origin[1]}",
        "destination": f"{destination[0]},{destination[1]}",
        "key": AMAP_KEY
    }
    segments = [origin] + waypoints + [destination]
    full_path = []
    
    # Calculate approximate segment distances for better shape control
    total_segments = len(segments) - 1
    app.logger.info(f"Processing {total_segments} route segments")
    
    for i in range(total_segments):
        params["origin"] = f"{segments[i][0]},{segments[i][1]}"
        params["destination"] = f"{segments[i+1][0]},{segments[i+1][1]}"
        response = requests.get(url, params=params)
        data = response.json()
        
        if data.get('errcode') == 0 and data.get('data', {}).get('paths'):
            path = [(float(p['lng']), float(p['lat'])) 
                   for p in data['data']['paths'][0]['steps'][0]['polyline']]
            # Add logging for debugging
            app.logger.info(f"Segment {i+1}/{total_segments}: {len(path)} points")
            full_path.extend(path[:-1])
        else:
            app.logger.error(f"Failed to get route for segment {i+1}: {data}")
    
    full_path.append(segments[-1])
    app.logger.info(f"Total route points: {len(full_path)}")
    return full_path

def generate_roadbook(path):
    html = f"""
    <html>
    <body>
        <h1>您的骑行路线书</h1>
        <img src="https://restapi.amap.com/v3/staticmap?key={AMAP_KEY}&size=500*300&path=2,0xff6600:{';'.join([f'{x},{y}' for x,y in path])}">
        <p>总距离: {len(path) * 0.01} 公里（示例计算）</p>
    </body>
    </html>
    """
    output_path = os.path.join(os.path.dirname(__file__), '..', 'public', 'roadbook.pdf')
    pdfkit.from_string(html, output_path)
    return 'roadbook.pdf'

@app.route('/generate_route', methods=['POST'])
def generate_route():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400
            
        if 'text' not in data or 'distance' not in data or 'start_point' not in data:
            return jsonify({"error": "Missing required fields: text, distance, and start_point"}), 400
            
        text = data['text']
        if not text or len(text) == 0:
            return jsonify({"error": "Text cannot be empty"}), 400
            
        try:
            distance = float(data['distance'])
            if distance <= 0:
                return jsonify({"error": "Distance must be positive"}), 400
        except ValueError:
            return jsonify({"error": "Distance must be a valid number"}), 400
            
        if not os.path.exists(FONT_PATH):
            return jsonify({"error": "Font file not found"}), 500
        
        # 1. Get character outline
        outline = get_char_outline(text)
        
        # 2. Scale to target distance
        scaled_coords = scale_to_distance(outline, distance)
        
        # 3. Map to coordinates (using user-selected starting point)
        origin = data['start_point']
        waypoints = [(origin[0] + x, origin[1] + y) for x, y in scaled_coords[:-1]]
        destination = (origin[0] + scaled_coords[-1][0], origin[1] + scaled_coords[-1][1])
        
        # 4. Generate cycling route
        path = get_bicycling_route(origin, waypoints, destination)
        app.logger.info(f"Generated cycling route path: {path}")

        return jsonify({
            "path": path
        })
    except requests.RequestException as e:
        return jsonify({"error": f"Error calling map API: {str(e)}"}), 500
    except TTLibError as e:
        return jsonify({"error": f"Error processing font: {str(e)}"}), 500
    except Exception as e:
        app.logger.error(f"Unexpected error: {str(e)}")
        return jsonify({"error": "An unexpected error occurred"}), 500

if __name__ == "__main__":
    app.run(debug=True)