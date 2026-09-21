export const vertexShader = `
varying vec2 vUv;
void main(){vUv=uv;gl_Position=vec4(position.xy,0.0,1.0);}
`;
export const fragmentShader = `
precision highp float;
varying vec2 vUv;
uniform vec2 resolution;
uniform vec3 cameraPositionBH, cameraRight, cameraUp, cameraForward;
uniform float time, mass, flow, temperature, lensing, flashEnergy, focal, mobile;
uniform float starMotion;
uniform vec2 centerOffset;
#define PI 3.14159265359
float hash31(vec3 p){p=fract(p*.1031);p+=dot(p,p.yzx+33.33);return fract((p.x+p.y)*p.z);}
float hash21(vec2 p){return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453);}
float noise(vec3 x){
 vec3 i=floor(x),f=fract(x);f=f*f*(3.-2.*f);
 return mix(mix(mix(hash31(i),hash31(i+vec3(1,0,0)),f.x),mix(hash31(i+vec3(0,1,0)),hash31(i+vec3(1,1,0)),f.x),f.y),
 mix(mix(hash31(i+vec3(0,0,1)),hash31(i+vec3(1,0,1)),f.x),mix(hash31(i+vec3(0,1,1)),hash31(i+vec3(1,1,1)),f.x),f.y),f.z);
}
float turbulence(vec3 p){return .55*noise(p)+.28*noise(p*2.03)+.13*noise(p*4.07);}
vec3 blackbody(float t){
 vec3 amber=vec3(1.,.24,.025);
 vec3 gold=vec3(1.,.62,.19);
 vec3 ivory=vec3(1.,.88,.65);
 return mix(mix(amber,gold,smoothstep(0.,.5,t)),ivory,smoothstep(.4,1.25,t));
}
vec3 sky(vec3 rd){
 // Stars live on a celestial sphere, therefore warp along deflected rays.
 vec2 uv=vec2(atan(rd.z,rd.x)/(2.*PI),asin(clamp(rd.y,-1.,1.))/PI);
 // Slow celestial drift and independent twinkle; zero freezes both effects.
 float starTime=time*starMotion;
 uv.x+=starTime*.00065;
 vec3 col=vec3(.0007,.001,.002);
 vec3 n=rd*3.7;float neb=turbulence(n+vec3(2,3,1));
 col+=vec3(.002,.003,.005)*pow(neb,3.);
 for(int j=0;j<2;j++){
  float scale=j==0?340.:720.;vec2 g=uv*scale,cell=floor(g);
  float rnd=hash21(cell+float(j)*31.);
  vec2 delta=fract(g)-vec2(.15+.7*hash21(cell+5.2),.15+.7*hash21(cell+9.7));
  float width=j==0?.027:.018;
  float aa=max(length(fwidth(g))*.4,.018);
  float star=1.-smoothstep(width,width+aa,length(delta));
  float present=step(j==0?.987:.995,rnd);
  vec3 tint=mix(vec3(.46,.64,1.),vec3(1.,.75,.48),hash21(cell+7.));
  float twinkle=.8+.2*sin(starTime*(.7+rnd)+rnd*63.);
  col+=tint*star*present*(j==0?.7:.35)*twinkle;
 }
 return col;
}
vec3 diskLayer(vec3 p,vec3 direction,float order,float age){
 float r=length(p.xz)/mass;
 if(r<2.9||r>9.4)return vec3(0.);
 float a=atan(p.z,p.x);
 // Differential rotation: inner gas moves faster than outer gas.
 float angular=1.5*flow/pow(max(r,2.9),1.5);
 float phase=a-age*angular;
 vec3 coord=vec3(cos(phase),sin(phase),r*.72);
 float detail=turbulence(coord*vec3(3.,3.,4.)+vec3(0.,0.,age*.018));
 float ringPhase=r*44.+detail*9.-age*.12;
 float rings=sin(ringPhase)*.5*(1.-smoothstep(1.,3.,fwidth(ringPhase)))+.5;
 float finePhase=r*103.-detail*8.;
 float fine=sin(finePhase)*.5*(1.-smoothstep(1.,3.,fwidth(finePhase)))+.5;
 float streak=turbulence(vec3(cos(phase)*11.,sin(phase)*11.,r*19.+detail*2.));
 float filament=(.16+1.5*pow(detail,1.6)+.07*rings+.025*fine)*(.5+1.1*streak)*(.7+.3*sin(phase*7.+r*4.+detail*5.));
 float inner=smoothstep(2.9,3.14,r),outer=1.-smoothstep(7.2,9.4,r);
 float thermal=pow(3.1/max(r,3.1),2.55);
 float temp=pow(3.1/r,.75)*temperature;
 vec3 velocity=normalize(vec3(-p.z,0.,p.x));
 float beta=.48*sqrt(3./r);
 float beaming=pow(1./(1.-dot(velocity,-direction)*beta),3.);
 float redshift=sqrt(max(.1,1.-1./r));
 float emissive=thermal*filament*inner*outer*beaming*redshift;
 return blackbody(temp)*emissive*(1.5+flashEnergy*.35)*pow(.78,order);
}
vec3 disk(vec3 p,vec3 direction,float order){
 // Crossfade two advected gas layers. Each resets only when its weight is zero,
 // bounding differential shear instead of winding the texture forever.
 float cycle=fract(time/32.);
 float weight=.5-.5*cos(cycle*2.*PI);
 return mix(diskLayer(p,direction,order,fract(cycle+.5)*32.),
            diskLayer(p,direction,order,cycle*32.),weight);
}
vec3 accel(vec3 p,float L2){
 float r2=max(dot(p,p),.02);
 return -1.5*mass*L2*p/(r2*r2*sqrt(r2))*lensing;
}
void main(){
 vec2 screen=(vUv-.5)*vec2(resolution.x/resolution.y,1.);
 screen-=centerOffset;
 vec3 rd=normalize(cameraForward*focal+cameraRight*screen.x+cameraUp*screen.y);
 vec3 p=cameraPositionBH,v=rd;
 vec3 L=cross(p,v);float L2=dot(L,L);
 vec3 color=vec3(0.);float transmission=1.,order=0.,minRadius=100.,captured=0.;
 float rs=mass;
 // Null-ray bending approximation in a Schwarzschild-inspired central field.
 for(int i=0;i<132;i++){
  float r=length(p);minRadius=min(minRadius,r);
  if(r<rs*1.005){captured=1.;break;}
  if(r>38.&&dot(p,v)>0.)break;
  float dt=clamp(r*.13,.055,1.6);
  if(r<3.4*rs)dt=min(dt,.10*rs);
  vec3 ac=accel(p,L2),halfV=v+ac*dt*.5;
  vec3 nextP=p+halfV*dt;
  vec3 nextV=halfV+accel(nextP,L2)*dt*.5;
  if(p.y*nextP.y<0.){
   float f=clamp(p.y/(p.y-nextP.y),0.,1.);
   vec3 hit=mix(p,nextP,f);
   float hr=length(hit.xz)/rs;
   if(hr>2.9&&hr<9.4){
    vec3 light=disk(hit,normalize(v),order);
    color+=light*transmission;
    transmission*=.24;order+=1.;
    if(transmission<.018)break;
   }
  }
  p=nextP;v=nextV;
 }
 if(captured<.5)color+=sky(normalize(v))*transmission;
 // Very low-energy scattering around the photon orbit; no opaque neon torus.
 float impact=sqrt(L2);
 float critical=2.598076*rs;
 float aa=length(fwidth(screen))*length(cameraPositionBH)/focal;
 float photon=exp(-abs(impact-critical)/max(.022*rs,aa*.85));
 color+=vec3(1.,.54,.19)*photon*.25;
 float halo=exp(-abs(impact-critical)*1.8/rs)*.007;
 color+=vec3(1.,.31,.065)*halo;
 // Keep the captured center truly dark; this is not a glowing sphere.
 color*=1.-.10*pow(length(vUv-.5),1.5);
 gl_FragColor=vec4(color,1.);
}
`;

