from flask import Flask, request, jsonify, render_template
import requests
from fontTools.ttLib import TTFont
from fontTools.pens.ttGlyphPen import TTGlyphPen
import numpy as np
import logging
import math

app = Flask(__name__)

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler('app.log'), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# 高德API Key（替换为你的实际Key）
AMAP_API_KEY = "73106bae7c543acc43670ce44c77f340"

# 高德API endpoints
RIDING_URL = "https://restapi.amap.com/v4/direction/bicycling"
COORD_CONVERT_URL = "https://restapi.amap.com/v3/assistant/coordinate/convert"

def calculate_distance(point1, point2):
    """计算两点之间的地理距离（单位：米）"""
    R = 6371000  # 地球半径（米）
    lat1, lon1 = math.radians(point1[1]), math.radians(point1[0])
    lat2, lon2 = math.radians(point2[1]), math.radians(point2[0])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

def get_text_contour(text, font_path="src/fonts/Arial Unicode MS.ttf"):
    logger.info(f"提取文字轮廓: {text}")
    try:
        font = TTFont(font_path)
        cmap = font['cmap'].getBestCmap()
        if not cmap:
            logger.error("字体文件缺少cmap表")
            raise Exception("字体文件缺少cmap表")
        
        char_code = ord(text)
        if char_code not in cmap:
            logger.error(f"字体不支持字符 '{text}' (Unicode: {char_code})")
            raise Exception(f"字体不支持字符 '{text}'")
        
        glyph_name = cmap[char_code]
        glyph_set = font.getGlyphSet()
        if glyph_name not in glyph_set:
            logger.error(f"字形 '{glyph_name}' 未找到")
            raise Exception(f"字形 '{glyph_name}' 未找到")
        
        pen = TTGlyphPen(None)
        glyph_set[glyph_name].draw(pen)
        glyph = pen.glyph()
        
        points = []
        if glyph.coordinates:
            coordinates = list(glyph.coordinates)
            if not coordinates:
                return []

            seen = set()
            all_points = []
            for coord in coordinates:
                point = (coord[0], coord[1])
                if point not in seen:
                    seen.add(point)
                    all_points.append(point)

            if len(all_points) < 2:
                return all_points  # 如果点太少，直接返回

            key_points = [all_points[0]]  # 起始点
            prev_point = all_points[0]
            for i in range(1, len(all_points) - 1):
                p1, p2, p3 = prev_point, all_points[i], all_points[i+1]
                v1 = (p2[0] - p1[0], p2[1] - p1[1])
                v2 = (p3[0] - p2[0], p3[1] - p2[1])
                dot_product = v1[0] * v2[0] + v1[1] * v2[1]
                len1 = math.sqrt(v1[0]**2 + v1[1]**2)
                len2 = math.sqrt(v2[0]**2 + v2[1]**2)
                if len1 * len2 != 0:
                    cos_angle = dot_product / (len1 * len2)
                    angle = math.degrees(math.acos(max(min(cos_angle, 1), -1)))
                    if angle > 30 or angle < 150:  # 检测拐弯
                        if not key_points or calculate_distance(key_points[-1], p2) > 10:  # 避免冗余
                            key_points.append(p2)
                prev_point = p2

            key_points.append(all_points[-1])  # 终点
            unique_key_points = list(dict.fromkeys(tuple(p) for p in key_points))
            points = [(p[0], p[1]) for p in unique_key_points]

            # 根据字符限制点数
            if text == "1" or text == "一":
                points = points[:2] if len(points) >= 2 else [points[0], points[0]]  # 只保留起点和终点
            elif text == "中":
                max_points = 8  # 限制“中”最多8个点
                if len(points) > max_points:
                    step = max(1, len(points) // max_points)
                    points = [points[0]] + [points[i] for i in range(1, len(points), step) if i < len(points) - 1][:max_points-2] + [points[-1]]
                while len(points) < max_points:
                    points.append(points[-1])  # 填充点
            else:
                points = points[:10] if len(points) > 10 else points

            if len(points) < 2:
                points = [all_points[0], all_points[-1]] if all_points else []

        logger.debug(f"关键点数（起始、拐弯、终点）: {len(points)}")
        return points
    except Exception as e:
        logger.error(f"文字轮廓提取失败: {str(e)}")
        raise

def smooth_contour(points, num_points=20):
    logger.info("平滑轮廓点")
    try:
        if len(points) < 2:
            return points
        points = np.array(points)
        t = np.linspace(0, 1, len(points))
        t_new = np.linspace(0, 1, num_points)
        x = np.interp(t_new, t, points[:, 0])
        y = np.interp(t_new, t, points[:, 1])
        smoothed = list(zip(x, y))
        logger.debug(f"平滑后点数: {len(smoothed)}")
        return smoothed
    except Exception as e:
        logger.error(f"轮廓平滑失败: {str(e)}")
        raise

def map_to_real_coords(points, start_point=None, length_range=(5000, 10000), center_lat=39.9042, center_lng=116.4074):
    """将虚拟坐标映射到真实经纬度，以start_point作为起点，优先生成路径并匹配长度"""
    logger.info(f"映射坐标到经纬度，起点: {start_point}, 长度范围: {length_range}")
    if not points or len(points) < 2:
        return []

    if start_point:
        start_lng, start_lat = start_point
    else:
        start_lng, start_lat = center_lng, center_lat

    min_length, max_length = length_range if isinstance(length_range, (list, tuple)) and len(length_range) == 2 else (5000, 10000)

    is_vertical = len(points) >= 2 and all(abs(p[0] - points[0][0]) < 0.1 for p in points[1:])
    is_horizontal = len(points) >= 2 and all(abs(p[1] - points[0][1]) < 0.1 for p in points[1:])

    if is_vertical and len(points) >= 2:  # 垂直直线
        target_length = (min_length + max_length) / 2

        lat_diff = target_length / 111000  # 纬度变化量（度）
        real_coords = [
            (start_lng, start_lat),  # 起点
            (start_lng, start_lat + lat_diff)  # 终点（向上）
        ]
        actual_length = calculate_distance(real_coords[0], real_coords[1])  # 计算直线长度
    elif is_horizontal and len(points) >= 2:  # 水平直线
        target_length = (min_length + max_length) / 2

        lng_diff = target_length / (111000 * math.cos(math.radians(start_lat)))  # 经度变化量（度）
        real_coords = [
            (start_lng, start_lat),  # 起点
            (start_lng + lng_diff, start_lat)  # 终点（向东）
        ]
        actual_length = calculate_distance(real_coords[0], real_coords[1])  # 计算直线长度
    else:
        # 其他复杂路径，使用关键点平滑
        num_points = min(15, max(10, len(points) * 2))
        smoothed_points = smooth_contour(points, num_points)

        virtual_length = sum(np.sqrt((smoothed_points[i][0] - smoothed_points[i-1][0])**2 + 
                                    (smoothed_points[i][1] - smoothed_points[i-1][1])**2) 
                            for i in range(1, len(smoothed_points)))

        target_length = (min_length + max_length) / 2
        scale = target_length / (virtual_length * 111000)
        if scale > 0.001:
            scale = 0.001
        elif scale < 0.0001:
            scale = 0.0001

        max_iterations = 10
        tolerance = 100
        for iteration in range(max_iterations):
            real_coords = [start_point]
            prev_point = start_point

            for i in range(1, len(smoothed_points)):
                dx = (smoothed_points[i][0] - smoothed_points[0][0]) * scale
                dy = (smoothed_points[i][1] - smoothed_points[0][1]) * scale
                lat = start_lat + dy
                lng = start_lng + dx / math.cos(math.radians(start_lat))
                real_coords.append((lng, lat))
                prev_point = (lng, lat)

            actual_length = sum(calculate_distance(real_coords[i], real_coords[i-1]) 
                               for i in range(1, len(real_coords)))
            logger.debug(f"迭代 {iteration + 1}: 实际长度 = {actual_length:.2f} 米, 目标长度 = {target_length:.2f} 米")

            if abs(actual_length - target_length) <= tolerance or min_length <= actual_length <= max_length:
                break
            elif actual_length < min_length:
                adjustment = 1.05 + (min_length - actual_length) / (2 * target_length)
                scale *= adjustment if adjustment < 1.5 else 1.5
            else:
                adjustment = 0.95 - (actual_length - max_length) / (2 * target_length)
                scale *= adjustment if adjustment > 0.5 else 0.5

        if actual_length > max_length:
            scale *= max_length / actual_length
            real_coords = [start_point]
            for i in range(1, len(smoothed_points)):
                dx = (smoothed_points[i][0] - smoothed_points[0][0]) * scale
                dy = (smoothed_points[i][1] - smoothed_points[0][1]) * scale
                lat = start_lat + dy
                lng = start_lng + dx / math.cos(math.radians(start_lat))
                real_coords.append((lng, lat))

    logger.debug(f"最终scale = {scale if 'scale' in locals() else 'N/A'}, 实际长度 = {actual_length:.2f} 米")
    logger.debug(f"映射后的坐标: {real_coords[:5]}...")
    return real_coords

def convert_coords(coords):
    logger.info("转换坐标到GCJ-02")
    try:
        locations = ";".join([f"{lng},{lat}" for lng, lat in coords])
        params = {"key": AMAP_API_KEY, "locations": locations, "coordsys": "wgs84"}
        response = requests.get(COORD_CONVERT_URL, params=params)
        data = response.json()
        logger.debug(f"坐标转换响应: {data}")
        if data["status"] == "1":
            return [tuple(map(float, loc.split(","))) for loc in data["locations"].split(";")]
        logger.error(f"坐标转换失败: {data}")
        return []
    except Exception as e:
        logger.error(f"坐标转换异常: {str(e)}")
        raise

def get_riding_path(origin, destination):
    logger.info(f"规划路径: {origin} -> {destination}")
    try:
        params = {
            "key": AMAP_API_KEY,
            "origin": f"{origin[0]},{origin[1]}",
            "destination": f"{destination[0]},{destination[1]}"
        }
        response = requests.get(RIDING_URL, params=params)
        data = response.json()
        logger.debug(f"路径规划响应: {data}")
        if data["errcode"] == 0:
            steps = data["data"]["paths"][0]["steps"]
            full_polyline = []
            for step in steps:
                polyline = step["polyline"]
                points = [tuple(map(float, point.split(","))) for point in polyline.split(";")]
                full_polyline.extend(points[:-1])
            full_polyline.append(points[-1])
            return full_polyline
        else:
            logger.error(f"路径规划失败: {data}")
            return []
    except Exception as e:
        logger.error(f"路径规划异常: {str(e)}")
        raise

def generate_riding_track(text, start_point=None, length_range=(5000, 10000), city_center=(116.4074, 39.9042)):
    logger.info(f"开始生成骑行轨迹，文字: {text}, 起点: {start_point}, 长度范围: {length_range}")
    try:
        contour_points = get_text_contour(text)  # 关键点
        smoothed_points = smooth_contour(contour_points, num_points=20)
        real_coords = map_to_real_coords(smoothed_points, start_point, length_range, city_center[1], city_center[0])
        gcj_coords = convert_coords(real_coords)
        if not gcj_coords:
            raise Exception("坐标转换结果为空")
        
        full_path = []
        for i in range(len(gcj_coords) - 1):
            path_segment = get_riding_path(gcj_coords[i], gcj_coords[i + 1])
            if not path_segment:
                logger.warning(f"路径段 {i} 为空，跳过")
                continue
            full_path.extend(path_segment[:-1])
        full_path.append(gcj_coords[-1])
        
        final_length = sum(calculate_distance(full_path[i], full_path[i-1]) 
                          for i in range(1, len(full_path)))
        logger.info(f"最终路径长度: {final_length:.2f} 米 (目标范围: {length_range[0]}-{length_range[1]} 米)")
        
        logger.info(f"轨迹生成完成，点数: {len(full_path)}")
        return {
            "track": full_path,  # 完整路径
            "key_points": gcj_coords  # 关键点（起始、拐弯、终点）
        }
    except Exception as e:
        logger.error(f"轨迹生成失败: {str(e)}")
        raise

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/generate_track', methods=['POST'])
def generate_track():
    data = request.get_json()
    text = data.get('text', '中')
    start_point = data.get('start_point')  # 格式: [lng, lat]
    length_range = data.get('length_range', [5000, 10000])  # 格式: [min_length, max_length]，单位米
    logger.info(f"收到生成请求，文字: {text}, 起点: {start_point}, 长度范围: {length_range}")
    try:
        if start_point and not (isinstance(start_point, list) and len(start_point) == 2 and all(isinstance(x, (int, float)) for x in start_point)):
            return jsonify({"status": "error", "message": "起点必须是有效的经纬度列表 [lng, lat]"})
        if not (isinstance(length_range, list) and len(length_range) == 2 and all(isinstance(x, (int, float)) for x in length_range) and length_range[0] <= length_range[1]):
            return jsonify({"status": "error", "message": "长度范围必须是有效的[min, max]列表，单位米"})
        result = generate_riding_track(text, start_point, length_range)
        if not result["track"]:
            return jsonify({"status": "error", "message": "生成的轨迹为空"})
        return jsonify({"status": "success", "track": result["track"], "key_points": result["key_points"]})
    except Exception as e:
        logger.error(f"生成轨迹请求失败: {str(e)}")
        return jsonify({"status": "error", "message": str(e)})

if __name__ == "__main__":
    logger.info("启动Flask应用")
    app.run(debug=True, host='0.0.0.0', port=5001)