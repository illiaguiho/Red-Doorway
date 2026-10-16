// Hand-written translation of examples/stripes.json (Blender material "Stripes").
// This is the code the Phase 1 compiler should produce on its own; each block
// names the Blender node it comes from.
//
// Use in Blurres: copy this file and Stripes.bmat into a project's Assets/
// folder, so that the material's "surfaceShader" path resolves.

Surface EvaluateSurface(SurfaceInput i) {
    // Texture Coordinate (UV) -> Mapping (Point, scale 8, 8, 1) -> Separate XYZ
    vec3 mapped = vec3(i.uv, 0.0) * vec3(8.0, 8.0, 1.0);
    float x = mapped.x;

    // Group "Wave": sin(x * pi) * 0.5 + 0.5
    float wave = sin(x * 3.14159265) * 0.5 + 0.5;

    // Color Ramp (linear): 0.0 dark red -> 0.5 cream
    vec3 ramp = mix(vec3(0.25, 0.05, 0.04), vec3(0.9, 0.8, 0.6), clamp(wave / 0.5, 0.0, 1.0));

    // Map Range (linear, clamped): [0, 1] -> [0.7, 0.3]
    float rough = clamp(0.7 + wave * (0.3 - 0.7), 0.3, 0.7);

    // Bump (strength 0.4, distance 0.05) from screen-space derivatives of the
    // height, after Mikkelsen, "Bump Mapping Unparametrized Surfaces on the GPU".
    vec3 N = i.normal;
    vec3 dPdx = dFdx(i.worldPos), dPdy = dFdy(i.worldPos);
    vec3 Rx = cross(dPdy, N), Ry = cross(N, dPdx);
    float det = dot(dPdx, Rx);
    vec3 grad = sign(det) * (dFdx(wave) * Rx + dFdy(wave) * Ry);
    vec3 bumped = normalize(abs(det) * N - 0.05 * grad);
    N = normalize(mix(N, bumped, 0.4));

    // Principled BSDF
    Surface s;
    s.albedo = ramp;
    s.alpha = 1.0;
    s.metallic = 0.0;
    s.roughness = rough;
    s.normal = N;
    s.emission = vec3(0.0);
    return s;
}
