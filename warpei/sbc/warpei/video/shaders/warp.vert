#version 300 es
// Full-screen quad. Passes the panel-pixel position of each fragment to
// the fragment shader, which evaluates the warp there.
precision highp float;

in vec2 in_pos;            // clip space, -1..1
out vec2 v_panel;          // panel pixel coordinates, 0..W x 0..H

uniform vec2 u_panel_size; // (W, H)

void main() {
    // clip -1..1  ->  panel pixel 0..W, with y down (row 0 at the top)
    v_panel = vec2((in_pos.x + 1.0) * 0.5 * u_panel_size.x,
                   (1.0 - in_pos.y) * 0.5 * u_panel_size.y);
    gl_Position = vec4(in_pos, 0.0, 1.0);
}
