#version 330 core
in vec2 uv;out vec4 frag;uniform sampler2D a,b,c;uniform int op;uniform vec4 p,q;uniform vec3 lowColor,highColor;uniform float size;uniform bool maskOn;
float hash(vec2 v){return fract(sin(dot(v,vec2(127.1,311.7))+p.y*7.13)*43758.5453);}
float noise(vec2 v,float period){vec2 i=floor(v),f=fract(v);f=f*f*(3.-2.*f);return mix(mix(hash(mod(i,period)),hash(mod(i+vec2(1,0),period)),f.x),mix(hash(mod(i+vec2(0,1),period)),hash(mod(i+vec2(1),period)),f.x),f.y);}
vec2 grad(vec2 i,float period){float angle=hash(mod(i,period))*6.283185;return vec2(cos(angle),sin(angle));}
float perlin(vec2 v,float period){vec2 i=floor(v),f=fract(v),w=f*f*f*(f*(f*6.-15.)+10.);float a=dot(grad(i,period),f),b=dot(grad(i+vec2(1,0),period),f-vec2(1,0)),c=dot(grad(i+vec2(0,1),period),f-vec2(0,1)),d=dot(grad(i+1.,period),f-1.);return .5+.7*mix(mix(a,b,w.x),mix(c,d,w.x),w.y);}
vec3 A(vec2 u){return texture(a,fract(u)).rgb;}float H(vec2 u){return dot(A(u),vec3(.299,.587,.114));}
// Signed range supports reversed black/white points. Equal points use an explicit threshold.
vec3 levels(vec3 x,float lo,float hi,float gamma,float outlo,float outhi){
 vec3 t=abs(hi-lo)<1e-7?step(vec3(lo),x):clamp((x-lo)/(hi-lo),0.,1.);
 return mix(vec3(outlo),vec3(outhi),pow(t,vec3(1./max(gamma,.00001))));
}
void main(){vec2 u=uv,d=vec2(1./size,0);vec3 v=A(u);float f=0.;
if(op==0)v=lowColor;
else if(op==1)v=vec3(hash(floor(u*p.x)));
else if(op==2){float amp=.5,total=0.,freq=p.x;for(int j=0;j<6;j++){f+=noise(u*freq,freq)*amp;total+=amp;amp*=p.z;freq*=2.;}v=vec3(f/total);}
else if(op==3)v=vec3(perlin(u*p.x,p.x));
else if(op==4){vec2 pos=u*p.x,i=floor(pos);f=2.;for(int y=-1;y<=1;y++)for(int x=-1;x<=1;x++){vec2 q=i+vec2(x,y),w=mod(q,p.x);vec2 r=q+vec2(hash(w),hash(w+31.7))-pos;f=min(f,length(r));}v=vec3(clamp(f,0.,1.));}
else if(op==5){vec2 pos=u*p.xy;pos.x+=mod(floor(pos.y),2.)*.5;vec2 r=fract(pos);float edge=min(min(r.x,1.-r.x),min(r.y,1.-r.y));f=smoothstep(p.z,p.z+.04,edge);v=vec3(f*(1.-p.w*hash(mod(floor(pos),p.xy))));}
else if(op==6)v=vec3(mod(floor(u.x*p.x)+floor(u.y*p.x),2.));
else if(op==7){float t=radians(p.x);v=vec3(clamp(dot(u-.5,vec2(cos(t),sin(t)))+.5,0.,1.));}
else if(op==8){vec2 q=abs(u-.5)*2.;f=p.y<.5?length(q):p.y<1.5?max(q.x,q.y):q.x+q.y;v=vec3(1.-smoothstep(p.x-p.z,p.x,f));}
else if(op==9){float t=radians(p.z);f=fract(dot(u,vec2(cos(t),sin(t)))*p.x);v=vec3(1.-smoothstep(p.y-.01,p.y+.01,f));}
else if(op==10){float n=noise(u*vec2(4,8),8.);v=vec3(.5+.5*sin((u.x*p.x+n*p.z*4.)*6.28318));}
else if(op==11){vec3 fg=texture(b,u).rgb,r=fg;if(p.y<.5)r=fg;else if(p.y<1.5)r=v*fg;else if(p.y<2.5)r=v+fg;else if(p.y<3.5)r=v-fg;else if(p.y<4.5)r=1.-(1.-v)*(1.-fg);else if(p.y<5.5)r=mix(2.*v*fg,1.-2.*(1.-v)*(1.-fg),step(.5,v));else if(p.y<6.5)r=max(v,fg);else r=min(v,fg);v=mix(v,r,p.x*(maskOn?texture(c,u).r:1.));}
else if(op==12)v=levels(v,p.x,p.y,p.z,0.,1.);
else if(op==13)v=1.-v;
else if(op==14){v=vec3(0);float sum=0.;for(int y=-3;y<=3;y++)for(int x=-3;x<=3;x++){float w=exp(-float(x*x+y*y)/5.);v+=A(u+vec2(x,y)*p.x/3./size)*w;sum+=w;}v/=sum;}
else if(op==15){v=vec3(0);vec2 dir=vec2(cos(radians(p.y)),sin(radians(p.y)));for(int j=-8;j<=8;j++)v+=A(u+dir*float(j)*p.x/8./size);v/=17.;}
else if(op==16)v=A(u+vec2(cos(radians(p.y)),sin(radians(p.y)))*(texture(b,u).r-.5)*p.x);
else if(op==17){float t=radians(p.y);v=A(mat2(cos(t),-sin(t),sin(t),cos(t))*(u-.5)*p.x+.5+p.zw);}
else if(op==18){f=H(u);v=vec3(p.y<.5?(f>p.x?1.:0.):p.y<1.5?(f>=p.x?1.:0.):p.y<2.5?(f<p.x?1.:0.):(f<=p.x?1.:0.));}
else if(op==19)v=mix(lowColor,highColor,H(u));
else if(op==20){float x=(H(u+d)-H(u-d))*p.x*size/64.;float y=(H(u+d.yx)-H(u-d.yx))*p.x*size/64.;v=normalize(vec3(-x,p.y<.5?-y:y,1.))*.5+.5;}
else if(op==21)v=vec3(length(vec2(H(u+d)-H(u-d),H(u+d.yx)-H(u-d.yx)))*p.x);
else if(op==22)v+=p.x*(4.*v-A(u+d)-A(u-d)-A(u+d.yx)-A(u-d.yx));
else if(op==23)v=floor(v*(p.x-1.)+.5)/(p.x-1.);
else if(op==25){vec2 q=abs(fract(u*p.xy)-.5)*2.;f=p.w<.5?length(q):p.w<1.5?max(q.x,q.y):q.x+q.y;v=vec3(1.-smoothstep(p.z-.025,p.z,f));}
else if(op==26){vec2 dir=vec2(cos(radians(p.y)),sin(radians(p.y)))/size;v=vec3(.5+(H(u+dir)-H(u-dir))*p.x);}
else if(op==27){float x=texture(b,fract(u+d)).r-texture(b,fract(u-d)).r,y=texture(b,fract(u+d.yx)).r-texture(b,fract(u-d.yx)).r;v=A(u+vec2(x,y)*p.x*size/8.);}
else if(op==28)v=vec3(H(u));
else if(op==29)v=(v-.5)*p.y+.5+p.x;
// Reconstructed from installed Histogram SBS parameter DAGs, see sbs-node-reference.json.
else if(op==30){
 float position=p.z>.5?p.x:1.-p.x;
 float low=2.*(max(.5,position)-.5),high=min(2.*position,1.),contrast=clamp(p.y*.5,0.,1.);
 v=levels(vec3(H(u)),mix(low,high,contrast),mix(high,low,contrast),1.,0.,1.);
}
else if(op==31){
 float high=min(p.y+p.x*.5,2.*p.y);
 float low=1.-min(1.-p.y+p.x*.5,2.*(1.-p.y));
 v=mix(vec3(low),vec3(high),vec3(H(u)));
}
else if(op==32){
 float triangle=p.y<=0.?0.:clamp(1.-abs(H(u)-p.x)/p.y,0.,1.);
 v=levels(vec3(triangle),p.z*.5,1.-p.z*.5,1.,0.,1.);
}
else if(op==33){
 float position=mod(p.x,1.);vec3 inputValue=vec3(H(u));
 vec3 lower=levels(inputValue,0.,position,1.,1.-position,1.);
 vec3 upper=levels(inputValue,position,1.,1.,0.,1.-position);
 v=mix(lower,upper,step(vec3(position),inputValue));
}
else if(op==34)v=levels(v,p.x,p.y,p.z,p.w,q.x);
frag=vec4(clamp(v,0.,1.),1.);}