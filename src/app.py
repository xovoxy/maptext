from flask import Flask, request, jsonify, render_template
import requests
from fontTools.ttLib import TTFont
from fontTools.pens.ttGlyphPen import TTGlyphPen
import numpy as np
import logging

app = Flask(__name__)

# 配置日志
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app.log'),  # 输出到文件
        logging.StreamHandler()          # 同时输出到控制台
    ]
)
logger = logging.getLogger(__name__)

# 高德API Key（替换为你的实际Key）
AMAP_API_KEY = "73106bae7c543acc43670ce44c77f340"

# 高德API endpoints
RIDING_URL = "https://restapi.amap.com/v4/direction/bicycling"
COORD_CONVERT_URL = "https://restapi.amap.com/v3/assistant/coordinate/convert"

def get_text_contour(text, font_path="src/fonts/SimHei.ttf"):
    """从字体文件中提取文字轮廓点"""
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
        
        # 使用TTGlyphPen绘制字形并获取路径
        pen = TTGlyphPen(None)
        glyph_set[glyph_name].draw(pen)
        glyph = pen.glyph()  # 获取生成的字形对象
        
        # 从glyph中提取轮廓点
        points = []
        for contour in glyph.coordinates:  # glyph.coordinates 包含所有轮廓点
            points.append((contour[0], contour[1]))
        
        logger.debug(f"轮廓点数: {len(points)}")
        return points
    except Exception as e:
        logger.error(f"文字轮廓提取失败: {str(e)}")
        raise

def smooth_contour(points, num_points=20):
    """平滑轮廓点并减少数量"""
    logger.info("平滑轮廓点")
    try:
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

def map_to_real_coords(points, center_lat=39.9042, center_lng=116.4074, scale=0.001):
    """将虚拟坐标映射到真实经纬度"""
    logger.info("映射坐标到经纬度")
    real_coords = []
    for x, y in points:
        lat = center_lat + y * scale
        lng = center_lng + x * scale
        real_coords.append((lng, lat))
    logger.debug(f"映射后的坐标: {real_coords[:5]}...")  # 只记录前5个避免日志过长
    return real_coords

def convert_coords(coords):
    """将WGS84坐标转为高德GCJ-02坐标"""
    logger.info("转换坐标到GCJ-02")
    try:
        locations = ";".join([f"{lng},{lat}" for lng, lat in coords])
        params = {
            "key": AMAP_API_KEY,
            "locations": locations,
            "coordsys": "wgs84"
        }
        response = requests.get(COORD_CONVERT_URL, params=params)
        data = response.json()
        logger.debug(f"坐标转换响应: {data}")
        if data["status"] == "1":
            return [tuple(map(float, loc.split(","))) for loc in data["locations"].split(";")]
        else:
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
                full_polyline.extend(points[:-1])  # 避免重复最后一个点
            full_polyline.append(points[-1])  # 添加终点
            return full_polyline
        else:
            logger.error(f"路径规划失败: {data}")
            return []
    except Exception as e:
        logger.error(f"路径规划异常: {str(e)}")
        raise

def generate_riding_track(text, city_center=(116.4074, 39.9042)):
    """生成文字形状骑行轨迹"""
    logger.info(f"开始生成骑行轨迹，文字: {text}")
    try:
        contour_points = get_text_contour(text)
        smoothed_points = smooth_contour(contour_points, num_points=10)
        real_coords = map_to_real_coords(smoothed_points, center_lat=city_center[1], center_lng=city_center[0])
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
        
        logger.info(f"轨迹生成完成，点数: {len(full_path)}")
        return full_path
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
    logger.info(f"收到生成请求，文字: {text}")
    try:
        track = generate_riding_track(text)
        if not track:
            return jsonify({"status": "error", "message": "生成的轨迹为空"})
        return jsonify({"status": "success", "track": track})
    except Exception as e:
        logger.error(f"生成轨迹请求失败: {str(e)}")
        return jsonify({"status": "error", "message": str(e)})

if __name__ == "__main__":
    logger.info("启动Flask应用")
    app.run(debug=True, host='0.0.0.0', port=5001)