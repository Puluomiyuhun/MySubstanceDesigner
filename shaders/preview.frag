#version 330 core

in vec2 uv;
out vec4 frag;
uniform sampler2D baseTex,heightTex,roughTex,normalTex;
uniform vec2 viewportSize,angles,cameraPan;
uniform float zoom,textureSize;
uniform int shape;
uniform ivec4 bound;
const float PI=3.14159265;
mat3 rotation(vec2 a){float cy=cos(a.x),sy=sin(a.x),cx=cos(a.y),sx=sin(a.y);return mat3(cy,0.,-sy,0.,1.,0.,sy,0.,cy)*mat3(1.,0.,0.,0.,cx,sx,0.,-sx,cx);}
vec2 mapping(vec3 p){return shape==0?vec2(atan(p.x,p.z)/(2.*PI)+.5,acos(clamp(p.y,-1.,1.))/PI):p.xy*.4+.5;}
void main(){
vec2 q=(uv*2.-1.)*vec2(viewportSize.x/viewportSize.y,1.);
mat3 model=rotation(angles),inv=transpose(model);
vec3 eye=vec3(cameraPan,3.3/zoom),ray=normalize(vec3(q,-2.2)),ro=inv*eye,rd=inv*ray;
float t=-1.;
if(shape==0){float b=dot(ro,rd),c=dot(ro,ro)-1.,h=b*b-c;if(h>=0.)t=-b-sqrt(h);}
else if(abs(rd.z)>.0001){float hit=-ro.z/rd.z;vec3 p=ro+rd*hit;if(hit>0.&&abs(p.x)<1.25&&abs(p.y)<1.25)t=hit;}
vec3 background=mix(vec3(.105),vec3(.19),uv.y);float shadow=exp(-dot(q-vec2(0.,-.78),(q-vec2(0.,-.78))*vec2(3.,90.)))*.05;
if(t<0.){frag=vec4(background-shadow,1.);return;}
vec3 p=ro+rd*t,n=shape==0?normalize(p):vec3(0.,0.,1.);vec2 st=mapping(p);
vec3 tangent=shape==0?normalize(vec3(n.z,0.,-n.x)+vec3(.00001,0.,0.)):vec3(1.,0.,0.);
vec3 bitangent=normalize(cross(n,tangent));vec3 detail=vec3(0.,0.,1.);
if(bound.w!=0)detail=texture(normalTex,st).rgb*2.-1.;
else if(bound.y!=0){vec2 d=vec2(1./textureSize,0.);float dx=texture(heightTex,st+d).r-texture(heightTex,st-d).r,dy=texture(heightTex,st+d.yx).r-texture(heightTex,st-d.yx).r;detail=normalize(vec3(-dx*5.,dy*5.,1.));}
n=normalize(model*(tangent*detail.x+bitangent*detail.y+n*max(.05,detail.z)));
vec3 world=eye+ray*t,V=normalize(eye-world),L=normalize(vec3(-.6,1.,1.5)),H=normalize(V+L);
vec3 base=bound.x!=0?texture(baseTex,st).rgb:vec3(.55);float rough=bound.z!=0?texture(roughTex,st).r:.48;rough=clamp(rough,.07,1.);
float diffuse=max(0.,dot(n,L)),spec=pow(max(0.,dot(n,H)),mix(140.,5.,rough))*(1.-rough)*.65;
float rim=pow(1.-max(0.,dot(n,V)),4.)*.13;
vec3 result=base*(.22+diffuse*.83)+vec3(spec)+vec3(.55,.67,.8)*rim;
frag=vec4(clamp(result,0.,1.),1.);
}
