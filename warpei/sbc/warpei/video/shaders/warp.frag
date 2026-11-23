#version 300 es
// Warpei warp shader (Report 7.4). For each panel pixel q it evaluates the
// forward map f(q) = H(n(q)) + poly(n(q)) with the 12 polynomial coefficients
// and the homography as uniforms, applies the inverse target map T^-1, and
// samples the source frame once with bilinear filtering. Pixels whose lookup
// falls outside the source are black. Identity mode (u_passthrough = 1)
// shows the source unchanged.
precision highp float;

in vec2 v_panel;
out vec4 frag_color;

uniform sampler2D u_source;
uniform vec2  u_panel_size;     // (W, H) of the panel
uniform mat3  u_homography;     // column-major, maps (xn, yn, 1) -> camera (u, v, w)
uniform float u_coeff_u[6];     // residual polynomial, camera x
uniform float u_coeff_v[6];     // residual polynomial, camera y
uniform float u_target_scale;   // T: camera = scale * panel + offset
uniform vec2  u_target_offset;
uniform int   u_flip;           // 1 = mirror the source left-right
uniform int   u_passthrough;    // 1 = no warp

void main() {
    // Fragments sit at pixel centres (q + 0.5); the model and cv2.remap use
    // the integer pixel index q, so evaluate the map at q.
    vec2 q = v_panel - 0.5;
    vec2 src;                       // source lookup in panel pixel units
    if (u_passthrough == 1) {
        src = q;
    } else {
        // normalise to -1..1, as solve.py does
        float xn = (q.x - 0.5 * u_panel_size.x) / (0.5 * u_panel_size.x);
        float yn = (q.y - 0.5 * u_panel_size.y) / (0.5 * u_panel_size.y);
        vec3 h = u_homography * vec3(xn, yn, 1.0);
        vec2 cam = h.xy / h.z;
        cam.x += u_coeff_u[0] + u_coeff_u[1] * xn + u_coeff_u[2] * yn
               + u_coeff_u[3] * xn * xn + u_coeff_u[4] * xn * yn + u_coeff_u[5] * yn * yn;
        cam.y += u_coeff_v[0] + u_coeff_v[1] * xn + u_coeff_v[2] * yn
               + u_coeff_v[3] * xn * xn + u_coeff_v[4] * xn * yn + u_coeff_v[5] * yn * yn;
        src = (cam - u_target_offset) / u_target_scale;   // T^-1
    }
    if (u_flip == 1) {
        src.x = u_panel_size.x - src.x;
    }
    // texture coordinates: pixel centre convention, matching cv2.remap
    vec2 uv = (src + 0.5) / u_panel_size;
    if (uv.x < 0.0 || uv.y < 0.0 || uv.x > 1.0 || uv.y > 1.0) {
        frag_color = vec4(0.0, 0.0, 0.0, 1.0);
    } else {
        frag_color = texture(u_source, uv);
    }
}
