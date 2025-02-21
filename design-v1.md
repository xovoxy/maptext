# **字迹地图**

## **1. 系统概述**

### **目标**
开发一个Web服务，用户可以：
- 输入单个字符（如汉字“山”、英文“love”、数字“123”）。
- 指定骑行距离（如5公里）。
- 在地图上生成一条形状与输入字符一致、覆盖指定距离的骑行路线。
- 获取一份“路线书”（地图可视化及指引）。

### **系统架构**
- **前端**：用户交互界面，基于高德地图JavaScript API。
- **后端**：处理输入、生成路径、调用高德骑行API。
- **地图与路由集成**：高德地图API（骑行模式）。
- **路线书生成**：生成PDF或图片格式的路线书。

---

## **2. 技术方案**

### **2.1 前端**
- **技术栈**：
  - HTML、CSS、JavaScript。
  - 高德地图JavaScript API（AMap JS API）。
- **功能**：
  - 输入框：文本（限制单个字符或短词）和距离选择。
  - 地图显示：渲染生成的骑行路线。
  - 交互：提交按钮、路线预览、下载路线书。
- **核心代码**：
  ```html
  <!DOCTYPE html>
  <html>
  <head>
      <meta charset="utf-8">
      <title>骑行路线生成</title>
      <script src="https://webapi.amap.com/maps?v=2.0&key=YOUR_API_KEY"></script>
      <style>
          #map { width: 100%; height: 500px; }
      </style>
  </head>
  <body>
      <input id="text" type="text" placeholder="输入字符（如山）" maxlength="5">
      <select id="distance">
          <option value="1">1公里</option>
          <option value="5">5公里</option>
          <option value="10">10公里</option>
      </select>
      <button onclick="generateRoute()">生成骑行路线</button>
      <div id="map"></div>
      <script>
          var map = new AMap.Map('map', {
              zoom: 14,
              center: [116.397428, 39.90923] // 默认北京
          });

          function generateRoute() {
              var text = document.getElementById('text').value;
              var distance = document.getElementById('distance').value;
              fetch('/generate_route', {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ text: text, distance: distance })
              })
              .then(response => response.json())
              .then(data => {
                  var path = data.path; // 后端返回的经纬度点数组
                  var polyline = new AMap.Polyline({
                      path: path,
                      strokeColor: "#FF6600", // 橙色表示骑行
                      strokeWeight: 5
                  });
                  map.add(polyline);
                  map.setFitView();
              });
          }
      </script>
  </body>
  </html>
  ```

### **2.2 后端**
- **技术栈**：
  - Python + Flask。
  - 字体解析库：`fontTools`。
  - 地理计算库：`shapely`、`geopy`。
- **功能**：
  - 解析字符，转为路径点。
  - 缩放路径到指定距离。
  - 调用高德骑行路径规划API生成路线。
- **核心代码**：
  ```python
  from flask import Flask, request, jsonify
  import requests
  from fontTools.ttLib import TTFont
  from shapely.geometry import LineString
  import numpy as np

  app = Flask(__name__)
  AMAP_KEY = "YOUR_API_KEY"

  def get_char_outline(text):
      font = TTFont('path_to_font.ttf')  # 使用支持中文的字体，如思源黑体
      glyph = font.getGlyphSet()[font.getBestCmap()[ord(text[0])]]
      coords = []
      def move_to(pt, _): coords.append(pt)
      def line_to(pt, _): coords.append(pt)
      glyph.draw({'moveTo': move_to, 'lineTo': line_to})
      return LineString(coords)

  def scale_to_distance(outline, target_distance_km):
      current_length = outline.length  # 抽象单位
      scale = (target_distance_km * 1000) / current_length  # 转换为米
      scaled_coords = [(x * scale / 111000, y * scale / 111000) for x, y in outline.coords]  # 粗略经纬度转换
      return scaled_coords

  def get_bicycling_route(origin, waypoints, destination):
      url = "https://restapi.amap.com/v4/direction/bicycling"  # 高德骑行API
      params = {
          "origin": f"{origin[0]},{origin[1]}",
          "destination": f"{destination[0]},{destination[1]}",
          "key": AMAP_KEY
      }
      # 高德骑行API暂不支持waypoints，分段调用
      segments = [origin] + waypoints + [destination]
      full_path = []
      for i in range(len(segments) - 1):
          params["origin"] = f"{segments[i][0]},{segments[i][1]}"
          params["destination"] = f"{segments[i+1][0]},{segments[i+1][1]}"
          response = requests.get(url, params=params)
          data = response.json()
          if data['errcode'] == 0:
              path = [(float(p['lng']), float(p['lat'])) for p in data['data']['paths'][0]['steps'][0]['polyline']]
              full_path.extend(path[:-1])  # 避免重复点
      full_path.append(segments[-1])  # 添加终点
      return full_path

  @app.route('/generate_route', methods=['POST'])
  def generate_route():
      data = request.get_json()
      text, distance = data['text'], float(data['distance'])
      
      # 1. 获取字符轮廓
      outline = get_char_outline(text)
      # 2. 缩放到目标距离
      scaled_coords = scale_to_distance(outline, distance)
      # 3. 映射到地图（以北京中心为例）
      origin = [116.397428, 39.90923]
      waypoints = [(origin[0] + x, origin[1] + y) for x, y in scaled_coords[:-1]]
      destination = (origin[0] + scaled_coords[-1][0], origin[1] + scaled_coords[-1][1])
      # 4. 调用高德骑行API生成路线
      path = get_bicycling_route(origin, waypoints, destination)
      return jsonify({"path": path})

  if __name__ == "__main__":
      app.run(debug=True)
  ```

### **2.3 地图与路由集成**
- **技术栈**：
  - 高德地图骑行路径规划API（`/v4/direction/bicycling`）。
  - 高德地图JavaScript API。
- **功能**：
  - 将文本路径点分段传入高德API，生成骑行路线。
  - 前端渲染路线。
- **实现细节**：
  - 高德骑行API不支持`waypoints`，需分段调用。
  - 使用`AMap.Polyline`绘制完整路径。

### **2.4 路线书生成**
- **技术栈**：
  - `pdfkit`。
- **功能**：
  - 生成包含骑行路线地图和指引的PDF。
- **核心代码**：
  ```python
  import pdfkit

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
      pdfkit.from_string(html, 'roadbook.pdf')
      return 'roadbook.pdf'
  ```

---

## **3. 工作流程**
1. 用户输入字符（如“山”）和距离（如5公里）。
2. 前端发送请求至后端。
3. 后端解析字符轮廓，缩放至目标距离，映射到经纬度。
4. 分段调用高德骑行API生成路线。
5. 返回路径点，前端渲染。
6. 生成路线书，用户可下载。

---

## **4. 技术难点及解决方案**

### **4.1 文本转路径**
- **难点**：汉字轮廓复杂。
- **解决方案**：
  - 使用`fontTools`提取轮廓。
  - 简化路径以减少计算量。

### **4.2 路径缩放与映射**
- **难点**：骑行路线受自行车道限制，可能失真。
- **解决方案**：
  - 使用`shapely`精确缩放。
  - 动态调整起点方向。

### **4.3 路线贴合形状**
- **难点**：高德骑行API不支持途经点（`waypoints`）。
- **解决方案**：
  - 分段调用API，将路径点作为连续的起点和终点。
  - 使用`AMap.Polyline`绘制完整形状。

### **4.4 距离精度**
- **难点**：分段路线总距离可能偏离目标。
- **解决方案**：
  - 计算实际距离后，调整缩放比例或增加绕行点。
  - 迭代优化至误差<100米。

### **4.5 性能问题**
- **难点**：多段API调用可能导致延迟。
- **解决方案**：
  - 并行调用API（使用`asyncio`）。
  - 缓存常见字符路径。

### **4.6 骑行可用性**
- **难点**：路线可能包括非骑行区域。
- **解决方案**：
  - 使用高德骑行API自带的可骑行验证。
  - 提示用户选择适合骑行的区域。

---

## **5. 附加考虑**
- **字体支持**：使用开源中文字体。
- **区域选择**：默认城市中心，支持用户调整。
- **安全性**：确保路线适合骑行。

---

## **6. 下一步计划**
1. 开发原型，测试“山”等字符。
2. 集成高德骑行API，优化分段逻辑。
3. 用户测试，验证路线实用性。
4. 优化性能和精度。

---