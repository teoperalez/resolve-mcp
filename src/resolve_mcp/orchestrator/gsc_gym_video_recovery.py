from __future__ import annotations

"""Deterministic recovery of missing GSC physical-battle telemetry.

This module is deliberately independent from the Resolve runner.  It reads the
finalized 1080x1920 vertical recording, classifies the fixed header mode chip,
and returns evidence-bound physical ranges already projected to the main OBS
recording.  It contains no OCR, learned model, prompt, or LLM surface.

Raw mode runs are never debounced here.  A caller must supply a complete,
named deterministic resolution receipt before battle ranges can be emitted.
That keeps policy (including any treatment of one-frame UI bounces) visible
and auditable instead of hiding it in a heuristic.
"""

import base64
import hashlib
import json
import math
import os
import queue
import re
import subprocess
import threading
import time
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence


FPS = 60
VERTICAL_WIDTH = 1080
VERTICAL_HEIGHT = 1920
MODE_CHIP_X = 852
MODE_CHIP_Y = 60
MODE_CHIP_WIDTH = 154
MODE_CHIP_HEIGHT = 56
MODE_SAMPLE_WIDTH = 38
MODE_SAMPLE_HEIGHT = 14
MODE_SAMPLE_BYTES = MODE_SAMPLE_WIDTH * MODE_SAMPLE_HEIGHT
HEADER_TITLE_X = 70
HEADER_TITLE_Y = 48
# The header's first auxiliary card can begin at x=548.  Stop at x=540 so
# the title sample cannot absorb the TIME/ATTEMPT card outline into its dark
# bitmap.  The compositor draws every finite title well inside this runway.
HEADER_TITLE_WIDTH = 470
HEADER_TITLE_HEIGHT = 42

MAX_PROJECTION_SEARCH_RADIUS_FRAMES = 30

EXPECTED_MAIN_PROJECTION_FRAMES = -6
EXPECTED_MAIN_PROJECTION_SECONDS = -0.100
PROJECTION_METHOD = "deterministic_cross_media_pixel_correlation_v1"
MIN_PROJECTION_ANCHORS = 3
MIN_PROJECTION_ANCHOR_SEPARATION_FRAMES = 600
MAX_PROJECTION_MATCH_DISTANCE = 0.12
# Projection samples may be long, normalized temporal pixel windows.  A
# 0.001 SAD margin over hundreds of thousands of immutable pixels is already
# a strong unique separation, while adjacent 60 fps candidates commonly stay
# visually close.  Keep this distinct from the much higher single-title
# template margin used below.
MIN_PROJECTION_RUNNER_UP_MARGIN = 0.001

VERTICAL_MANIFEST_SCHEMA = "gscnewlayout.vertical-recording-manifest/v1"
RECOVERY_SCHEMA = "gsc_gym_video_telemetry_recovery_v1"
RAW_RUN_SCHEMA = "gsc_gym_video_raw_mode_runs_v1"
MAPPED_ATTEMPTS_SCHEMA = "gsc_gym_video_mapped_physical_attempts_v1"
SEMANTIC_RUN_RESOLUTION_POLICY_ID = (
    "gsc_gym_fixed_header_party_replacement_merge_v2"
)
MAX_FIXED_HEADER_SEMANTIC_DISTANCE = 0.12
MIN_FIXED_HEADER_SEMANTIC_MARGIN = 0.01

KOMIKAX_FONT_SHA256 = (
    "D2C790C5CE96E4453AB7EA2D17F8C71DB06CEC3D3AB4F7F98DB02955E63AB353"
)

# This is a finite raster atlas generated from the exact KOMIKAX_.ttf bytes
# identified by KOMIKAX_FONT_SHA256 at the compositor's 32px title size.  It
# contains only the GSC leader titles and RIVAL1/RIVAL2; it is not a character
# recognizer and cannot transcribe arbitrary text.  The payload is assigned
# below to keep the contract and matching implementation together.
_KOMIKAX_ATLAS_B85 = (
    "c-pm{X_unN)~Nr=u~nAC>s<lPFPaI?ir|pWAH)#{oH11f`R#W{nAKffiPk;m^z9F|wB3maJDxqp#{45&;>CKoCjG0*OWFJ%|7-p+S)H{%{`U_QJ9b^jG^aK~h;AbKYI7*uD9#YAXG%&YpwEz|wPTf`cV9s$85OyVJS&-2Zf2NTWY$k=M_oypoRXl0RL)~s*^iYnOAazt@}669)3JJEwu|%?X}iEic26Td*{zH}5gOPge6Zg~qe?@vq}@Ta#J8<28@@g@vbXHOl7!^llFD{&e$V+Ma6(D1$#`ruV*0%TvsK*@W^-c;s-%m0$R1zYE_<P$xq8OrWIdirEN`Z$SyE$Y8HTL%%{zVQSea{9w}f)~C@hf52&yL+g`?E)2XUHWo1;FQ`1xoy=7P!Ba^o<wUF(<mdjqMa9^fJfu{DH0p!rISx>-g4@x*z}$(<{ITo>k9kNDVFVd|GtpK8oBn@xmbe&GUt+bo)mt=r<OsCbVi^sE0c2=u~-?rG#!CB76IF-0-XWj42fD!IBf_QX;r6bsBc=J`6R3)9@tvT|JkDfG5-6*iycbCmDx7Q%Sy&lwjcmqLgUY4f!6j^^*ReG*RczOa(=70ut9?ku8jTX<EYIYHS(1@mOfE*JAr*s_g{C0OC?T5+{*GSBA1qH1bL@uOy@d@yx?0fZ^an%~9FJ71co+lRp@hp(Tq;)RfAo2TuW57}!^=P<DPDP_7y_EGMzs+)|P+QNz7ljQnYVZO0YGKboP7ktJ0<AZyCQs*+eQ4^i~?;|so4ejQZb+SfGb2o$=Kao+mpP?Tg+#^$DiPV08(6|;}48&_JWH*m3OAON+7o%{Mk=+UHX=$3=hJprvq-#>foCg+%wZ-=nC1ZDACxmTRwS_)Qx#vpL=P~qi+dOnP$vHkKLd|kG4C?6aTSad<ZtB5_VCr78GCzlS`1xJ5vU07F3vO*8EbGPQ5Wb^-vZO<bHye`w6JNEe>05N(P`GRBmb5qArdhHWxZ)%79iUQb=;JWx_Lp2n>#h~5brxhjspiQCs^r<{XlcNj^F?7XnTJaI3!HeH7W!^~Md+K}vY_5R8%l0<yBb@m(S^mNr%-Mh4si9jy|9WN%_~!W_r;85*fOZz+eYYn>SO%D`+TumY6wMU+mskt=By&sxNzQ9bAhx<_-(|LdI=PxqEq<bBW`B>TosnfdnTG(PfNVuuO6d`_XeP#j9SavkqUvv>Ra*wvn@o8^ybc}Li4>mo3GWlVe}6@8h*!k5X~lX7ToxZ+sb_e+(yr{wuQww2<s!b`~W31(|k#a+Fb44ZUO}cE|ZSv6x^-Ff-i~kR@k<CHCa!LYs*VC4r<XgPcDm19?*%BX&1x0!zetc9`Off*}Yi%t*T4|+gzng(tPh95Gw7q2qh@l;u!^n>`BA__@FUQCQvhB+DI#z$0XYJcFSI*X#f*Z5z!Kx#joOqo}!k(#O-Qiw{;8sfBo-||M_G2$Nz@u|M^2(8FP5W{LdfPKmM0VqWk~+k*}6p`F|B^?dHES&9+qgndtxaf6)XR{!lXMghsSZSff~!e4s?^uqT?SW<r2hw<c_7&6c587WHAbcgezq2sdH9)v{c<-5;aqow;zC^*m^537ZSEL*a&wqcRUSMXbnrz4iu6cbkUWz1k|7-o`&)z9|aubQ=S`-*(XH?J|-n&VA-<rQQcDt1&D@Eouwf{`%9@LfsO4kgS0seYU|aSghGNjps^6U!*MQ#G0_chF~zp$YqJPE=T!kykkkFR2J4?{t6(g+CTwuX(jD)TE10MA^5YJF|xaNoul$6nyV)^SMrO%8k8@B;%nNAL2EHn3Kcai>&w~DMCEcAeu8i_eVe%gWSyvBnWF2^{V--+t#jWuYH8O3DEa^tXV#Bn>w<)p?H>cF8*V{48A_DzUu`fGvz`g0lgvw3ZnJczVZe9PBVfGhpN0|hMGpNzdSaw5;*iVB+o{ku4oj<a_7wS2pFaWqS%gg>!sJKMjMUZH#wDy_dfUS4-e1h`I~VN{hl`!zV~!Ip+ch}Zpx7Z8C9%Mjo7)(`%@)8o>=uVsT{$fV(@j9W3G7r*c7Xt+hHMVLXp7)&5DC-ly8s9M1f_Z3#=u~V>LdHZRg&HFdQHhKw|)4I2?zS(=>nj#)k9a;ZB<h4!Sv>x@|(WH?rv3wxhedFOdBrK4KXTPiz}dH0xtx*HnBp)fSWp{bWJNi3v<bUJ7D-CYzJSa0GAWCBHV>Vl8sgDcQZ$OYuI5)5LIC|qV3_5p^2zuj1wPCT<ri~EAS`$cA-Sf&|S&+>K;%efRWJTjNzb5Pr!g1O)J-lH&~i?2MG1xZQ^8{4xu}E1@W|1HKnbKnOsUE>y!?`z4QT_y5mVSaoZLQU3zo#rEw><7}U%W_*0n<=ri?co^R2cRbCteN`2Zs8OE?(Wtq?<h;k<%?_y?}DyQ7h53qD#7B~0xEt*W$bjoivV)MXCcSoa=tIC%;sna~L-1AmAkq6(bSDS%3_J6>7lXGcR+1p^dYdng1?W5s7wyUs0_Xvf1%uyKZy*X_1+X@wD?x@MfZyd#6bMt^Yyn}II0lwY)0_bSld}%l8EU(@w7#2Fonb}l!YF>J!wUxQ>P1I~yx)KOcD||n|UM8%(t2JA1x#^tpp>PKc=iB>v&X>#YYan&5Y)Mnm1&6n*fbeP+Yv&B?xx|>UoMpk!I?%lEo^gS2DFAK{tARJ79+g6An+E^tT*Zt)d~UP|Vf)dss`t6V)tPjUZD_;G$R1Q@!nV`ld44k&4E>{40ie_*tH`N+E~D;>Y&JdO0Tfhu9vHf(pgFSyu|lAt*CJ}X1(79GCIMwyt71h;UT3U_&JgAx?WBe9P4-3Z(_#k}gw9oJnVt?S^sP1B&RkKt7OlBZ{glknLRt(fiGCx4P_W)csN+_DV743s>oUCKmo#t^?mn0x4!;fmgZ3ee5`VW30^iI_|NrcR4|_~~tok&#4N?mhRjBgHJ{T&~A4aQiS<kd3Bm?c=+6OSazKA;uw_R<9%&>u8+XrT&_hG5`2SHd=tpUUXR`I2Mhyc7AVUzLR>)5zA!6!X;UfPGKpj?|4e47{qk$n>u?!EKEJ^)-@jM}t7Y2PL!=J=g`SR7a8Y5zW&pQ*RXh^c>k{>DB~(Q^>ilRdR~)Xtk4Q?OszhXrGr?t~1#qh`bDO6P|`cwryd7%iPr7jRZDOA>v&whz3x;47Th_ZEVv$2-Hp&H0smuxYsaY{<-7;FCdMIm4Iz_QF1ZAIRk@%j2Bo<`mp%sr@hrPwfM!8Ma!}8bk{*ABjU=+Xwvr;M<gd%hgIvTyw<}mw#g)z_ZB0x4A*h=1Wu7Gr_@Y`vAO50m=`H1z;9JIBXDJ*oQ%}4ch)$g5}baNksD6J_y^op;(gG8)MJb5;hwl`_eu@T+`Vu%*MrSL2y$)Luke|Uf2hwYAf~m(Sn;Cc!$uZviXgDi21AVy@zHWw8WP(Fa1;DwS5q#8BZEDY|jP4`*i{Is$P6)AKa>NkZWc`{InqW_titTQp>!s51Y%G^Sb+9la99T@Mj74Z|p<N*z0g{s(xC$v?&s$ytWTXD^Vz;#wgZfvv>C%CrU0a?L!>lXnn@2+1WoGKZJq9f42{{BL5$o2l^KIK)KHtSTfeVN3lR}gAuv}#icwDdW~`7=x`%yL)S!mjSiBM<)&=kN4zgC!+x%ag=N+mwgGqZ3ZFAKimw%|EWRF~hVg6~lwOFMsK}5%!$gqU5Zz@{AzOQ^{oWpY0$fsv%b3Oj3)is4rhf=;FXo*-E)HWl5W>O`vzN!&AHvBZ5r(*SdIjOyjtIjC)ej(QuYfaDAF?j98ZWhzHCn>4{`NzU!D4G)A$kwnKzu%e&5b;2HI>Cf__qci%}qZq6-;9lOm4gjasv}bV+la58WE<s+2l+3aOrZ>t9*C}V-SPz7X8WP1m<!TU|$8J5C~9gV_*3MtH-t-gdY$W`li1M-xdwHm~N={L-;que*@>ZEy`3Xgq_NI6blCcu;T!JTYU)Isbv<fAJ6<Gye)ZMaL^DJ%|>!p@)oD5szCP%R))}3nK9eNI42EG!nP4|LkN{Y(QIryA#bs81ym0_+gedtC^JAR%5BufZxNs66>4f!m8qNnVJdgR!Y4S2h{)S7VQ(1Rj%>PvG_6d#n2)#UpGQ7@9r?IP&flf|4e&Nr_*&v4g|vZbvW>AOC{dK}K7_@ESR`*BnC2}s;3ZpRLCx}aR*Rao-!k1LfN*a95MGoH4|?*v`jIBW5IB_}>K)kjLl_KqG9~Hx#xKIAMn_IWn4~5JW#zJ&4Ohz%VVr;!zPMc1-I&W0GnTP=FwzweR&AS6M`r=JTyp;w;;tho^+JbWlmqLy`EVb^ZWsyM?h1i$IVQVjS)a*xLY6R|xW*8dz4OaYb39TqF0TN>OqE<`@V`)m%a3kT0JdZaRryL=#Z=Y<S65$y=1>VDOcZHkw^ImQf>aYcCqxO=<t2?BBmu7OH1}I-XFp8yBmcoD#sPc0QVTVkVBvoJ7elCI6JUcKthnQG{d~=$`MqBJM>0K$*xyOrEmy1mA*l=Oyg&RzIc=CH-XlxLTTRUGg`rp4B0{-~YUrY;_Zrek^R3qR@J-`N{I6l(?6|RO%{_eNda>OBZ!|cBplburXC-Z9&vf%OpZU^23|V5koWd8o1EkhvkjsKvFh$p>Wz3UYJ(nnw)Gqkf5`5d1vR<PZ0%M;S4w?;tjz=XR+!z6=vtjHCf6}!ib>r&E>)U)$RCtKbmC)m$FR2WUPs-vFYIBB9twa24S{jcd#J^^?*}x|^^}2%ipjoWS7tp%#@HLS6lArE`%#^nd7tykQb=vts;E0o>Z+NYqaT>h-<DjotT&^_ohjw@pBY9=KGz@Gs4XmlvuY>L@etb<YW_B3NgSnefzrk=N_U09qQZNn&-Fy<?9Ag+9+v*8@`R3p)!`<JW%!V?`;CLeV8v?^YJ$S`~!QI`PhgQ)Z5pS8eZHJa%rpZB-Oz^hAAyJ1#l3V=^d<9=b{&7%i_ooXE*EF*7fNpRd?1HC>3$E~XHAD{jn_NpR%ThvZeu0awl=+{X;s{Pr&(m#iiramB(6$2ZXaPI&vDe7uYhmg#XWwSvrmh1Ap>NsmI5XBEE>kqB6moFTN*e$C5ILwTBFy)%X&cQLBMEMqu7Znu6(7DYJ}CIU?J7yOLfCZ*;S9J-ScmP3RbIMduR)8Qoy2^-Kh}V`*$!XJS#J16TtvwX7jxi7jkWk#dIonN1@UtEv`U}(`)kI6P6nxpd`hr5ep&)(+ijXZc78a;+Bp6r)y`<}!SVzSUvvINO!O-;<1`Snn&)%*=D#vkzAWYc176ZYPRo(yfb$z6(BTv)N;0x+v&S-zVxdonCYF>ta-Zlo@a2MG@I+%F*}Yid+z}rD!nS1>dNWj#{li*ngIwrJ{K^s2Zx6v|j%47j0V5mT_yHoXw>vln!46#NV9=7r+dTX~P62z92$50~d*WJsz#_lI>#p!OxuJmNWH?@o`9%)bK_CoTYXt!5qWD9u9Ai&rntOaN$YpWmB!ctgXS$X@c_4@jpMI7b^%Sz+NimbFXIDX5Vh09lmJ>GCzB_wzyKAIQC@A}0@gY}kZp9yRNg5PNGE-95Y>e#ec7)}?@a!r>Hdao(f!qz;w{jtjq2ztY-DOO=zvQYJ4S;($L9Y2tuJ1`zarJFL<d}^CTGZqd4UE86N{YIrA98H^ORk(+G8=zOM9tiy^{3nt3|pNdX&|Htg+0intIQ@68sqC{Kv?hFr#G$qW;pP<7DP^=BA$eiV$o@-ce;C!i|>Dy^VhFH7neY4mPRU-MIa|Zu-uHrxr{ck)2gzb$a>6h5jofWG7AzpkK`SS;B^)ff60NxYiN(-^#d8n#mqk8c<ovR<cbH7>-#{ir;uVC$Qfx^^g&ahI@UXQ(TzRQCPkggxObs1xlQAWb4CJ@TMW1a#cWr*7ShVf9>-Yc^vdou(yBC5K`!S4$KV=S-mFeNnvHJ)=;ZUdLUxL|fO#zUJwjW)|0SnNt8y<Ivs@E&@^i^=avZY-PkvB0ZsX=T8sn!R7s{vD+$v^+T=AV^>(mXWF=n{XC;$hoKs0)5Odvw!&Q|IC-r^E#&JTgjFlI^fwSqBrByOQvs{2Ry`W3Bev@rp5c^<10cUuyM8tQIfV~?<^mWp01mn~RTF1-dh?E=@79bntS3e|+~hFytv<UUJ-9yEf;s=m8(L~b#Tr3w)5QFB~RlmGy%i|N0!BODPAEZ*Oh(@I;j6^dCX*oo@U!(qYm<$IA7aHH7eGPg*V&BguMf5d%^qMu>d{x?zhih_j<aeQ9@Fk!Eh`dqbNurJbFLzI#De1W~rVhbxLn0i6HgcSn=aWP-O4n*K6KK2FYh{(;CdVx41(%l7L&}|#c$+u6GegU?vFDu_FM(_pGKqS4%Fxm^8)jNqFBF{*MMet&M0kP$zmfo1n`wM=72;e7re}OJ@UnHyU1+|DsQxRVP%bc!YO=g-eSVcslx5Eoev7QfASfb_&Lb2XBIC%NV3po8H@{~)<z#e;p=@&?<oJ+)udQKx@?B9|!!*dV`6Z%Nb{yBq$=4eB%!3+E_#~`WPydaOdo&LAHq2oXCrdi7h|D^AQ1HB}i_4_EUfA+Rd(F1WyK7zv&MW`nI)2IBw2^}}CGfaiPzvy}fA$WUu^O)v1VLyVkCnOp|6dcwpzF1lPCFg*nA9DSUszggk&r>E@d@tP<26@wqOZdzSFb$|QiT36;8bzMa=`XoFKetnz#4|+ErpA^=5R<ve3cX#_o^gtXYp}6EZptf>`+WNpRwm=+vD~C%B~3H)lvrjC4HLXTp*CFcwD=5Lml4yw6?nmG-*C&|@)^5Sd^y1bhO>ej5JS%Z7KYonv4xdYJ&|<TGm63ODG#VGxe{wVL)iw@ajW6fSQQsDhtGKSX%z#77(~Goco8xRK7-m6mmQ`Gy%I=qboh*H8u{Kin<{pHk^4K|Xs{dmscBz)x_R1aqi2i*x4M>Zo0qoXCqDf%&~4aLD$y}7z39$t%r53L+9gP(-lQYhftlrQvuDVQv$=5pg1f)mGL@?3pK{M|?{ir$+d~`KJ+G-x;b$1Zu?!9;Ez5>C*M3I8&Q}>80{N27%Afx&3nR&&SlBLp^#6Sp#&E)s18%3MaIRXO+49>6YKq$>?#f7`*m0DH-`SFoc9Ln+bT?A?RUM+mFjx*zV&MXqTPt&k_en*Olt5Hz$OkR)O&h|GT`$=Bd&pKYz4ko4+P>$XVi4|}n=-X=N#=5uDbA>-DL}1}GS7N6OO`B<Z8(hb2OZ%qMh=ukM4*9#8SbUJ!Yd_-i*=$U+UEp#ei;^4(oQhkCuIVW9Qy&MR_%;z%8KJu2*i@UR?75k!~W5I-A_L!;Q3Z!=j^*{EvK%5Ps6Q6rh>ArEre-qJU3A(do|5<0r8?@?}hbX-<aPE6oTVr7dS=aKXebFB^ZiXfUZfk4wp;^(jF;u5pWH>1DB_oR)w{A#U(BiPK`1~_tD1S>dDJ_#Ke>77x43h_Chl?vSAVVbX>5^;GU+4FwGbype$1`edkRBbFTyZR=JTqs91b0(Q66QY|1_ihIyZryz@(|8q0S>CT-`JS3MBK?X?{+H;D?)kS#1ec;17ZjG^UCO)d<*dQiD~u`E1w++^xat#aiL*G%D)(*SO|2+LHu@56RCju|2YINLa{Smj7n6<>%9?!nAjxekwCtv^EcIB<q9PjGOtSr4|mb(B+Wfkm~3aS(S*242;1w`i>65&2#JFxZ=K_`;%R$XnnG>jpnKa2NV+FWd!VI>cSHGcy*?zv15PGpzaT6gMW6VL|MwN@loS040Q>m1}iZ_*I+Btd|~PF|NG}ebZGDl!M|%&7`=)E!u-atC(M#=WA>XkxY8*5eu=^Vlb_F*jTRAeM&pd>rp(T)^g|)s&U;7H_vJ-h2q$4q~3ZHSL-~M;Hs70;l@jQODLYYxMkjc^swg4og1#2AJnm#r14@J0l#+*AZ5~na_2j1g~N;FQqM^v)3UTN{@WqWyAQ!yz%r?ebNd<Sx?m{ii;`P?UMoZIF7Y4;eLjx<A_~B-o>Vev2DiD&k^erzj70vTT(;EyPdq+n$~9)|VVDg{S(K~z3?wZ0kptzzrfEdx$h_Bei!Y3(xGm%KjdG|KcUgWf81ze@VozFN?npUs9$DF~+_ZVH%?wN}B#Taz!*%H*phRE5cSH`1%Hmx4uar9>OKj)1RPZw9fpR{c%ga0TjdC+OG3?(rChjXz0V><1Bjs{h6s+NUayWl)*eNqs;Nwn|1AzFrM^$)%dZrSk>mDb{EpN+R?$Fge$YsZRW!xBga-y7k9bXfqQarM=n~5{!%J~sj&&7kL@34X&SUukyC|3mUv%LjIpA^$vy@7WUnb_Ycms_Gt+`kqSADH8)WgeX=SF-QSS~$&IEtNEKY@NM3Q1KjgGY~i?R~#lVO()8c1~uFpY>{;56Ux15xV<zF4!OUC5W8tPQ*NBaChx=nN)|KX>^V~IM4gkkxLO_2cRu=PVR51ytZ+9exRR43$$KZtMMAUH9(VBY%y{1}KcQTz4&K<|xV(DH8!C8g$DAn#F1M={t{&Nj8XBinX`wn$PBa_46iX_$^RsXAA?w99_nmSv1RkU>K#J_9Wm^Mh%0<=+&s!0WxPsAWH$Qf!T(JA5c--<Bw?W~qH!0~vIYteIrUQGJt^-wum4AS8v7abc<;%@~mvY)T1}DX)NK*_h*_rq>huF4CxOo*8MRRv`2HffpqHATdh!tmrf#kxwsc^3n8zqqqd~j}p=1C2i;{3y>Y$Mw3vNMc_WrFDd35S72MHa_BcS9GH6V7jOR;l9kSk+M`_ylWN_#n2O;9iR>oREvco1r2g7rT;OVZu7}Nn-K2**Kqa&xm%z*?ZG<_f#w3i)?C-jZdP`<01Utaj*_WL%vm9#n5oNe#4uC<R>uO4uB#k4VNx_!``HbH#u#D)x8%6pbv(om2Yq;=1T&LifisU$1=Oo)g#ujEw0>{Oz?8E0f|-FFk%<c&?n<MtOq5`m&@{6P(AsrGr~sg3<N~V2}0WQUMW-pJu{XKh9I8ynD~~FI*5f^uzehrKPR5jD`ac#I~CyNIH3*PnWISxqE_j%AQBM5HCXugN>rW#Q^$%kxUP0^)VlfU$IdBm7G@YUJu93U&v4mI#V168^E;TcS|nI|#;m%bpS3#W)j!v`tIvgzSU5=KR-U9@;DlJ2FLm+$x}tjsOsH{=xJu=BZ<chlhoErB0OKkJJyy|M>fk2MoktvM5+=(SZ@l|(-I2jRB^3lW=WA$4Tj1I?BMNERI}B|7WMw{SU_!zKXS#5WMiW{%KfjAR+Zj@W!W}}Sj|15P0B`dN+{Zow&{R~VtTMP`(f$ktsj9r_UTeo^eDVR&PATe|Mi-^Pd(wFASCwuf>;1t3@O6Zgs545i*ZwcL6#l8$nQxYbf4_^b9K$W>BU#S`F8GyAYOO-wYoC~1Q4(;cX!TjDZDNT&ZA#*6T=La0E(#bIXLvPDz?F?Gh@$dYp%qc;^ABe@<vt_0(}>T)s+-4TJuw)<0X9vt1qWNx943zkr%C*{`M|BrGQF{5f-UzMma)li18SJi<4~E)U`Zebri{Nb>&&6dG9lL|@L`M;YPy&>6AC;JypPjnPZp!$${;>_Q8u<>dU5DCtQ#EaXefoUURCIgkD;Xy%RNb}g*$96TwSC$Uf20?s6R;tA>FAAZ}X%N_XLnAXPJ$tr=DOc?8fcSi_m@N?vd6GzSMa?KA_kt8ksL=!mq~W?@c=zO(w@)=VV$V_^C<<re_HPs)GuE?WkpkEI4g$ypL0#J=R97D4eWtc7ynmFST=Kl@>EBq4@@`8v5|zs^<Wf+1VtAGW1esPb%VgE2Rzp3|!zwxk^t`XfeYy$6*&RC_jH3YGwOpu(IEJ<Q3Q*ZH3pG4u@*o;B9T-97>jC!_*RKOvah=HyS0z<Q0xyx1coi(#+AfDQ;wXk~pJ22lIPpJ)Z{->jmzMMg$1P&aBt)D+E7q3~oF+HqES62EO9fWCv;iWOEa~in4RuUnvs5Ny$*zG$3ieP%_^AlvMG}Y@j%kQ|Ep}*6UgJNxCdPV>VoFfNwH|d(HcNjo&2sOfNVB)0B>oAXQE^Gfg?QR$5%fUH3Sm3(QLi)phTj7QHDQ7EZ55@DRDLCZk_>gXH$tcAM3$$bX5i@L%{U@Kr&|H~+)twx^l0v|%huDxz!m73tUjW2Y4z{4BRs45o+pq6kT!@9q+|b(V6DCX+FQH=}&u{`nJFl;z#DU3K&<ai%Gmff^#aq+PAlRx<RmZ}KF2#$?P`?*4&M@oq_4rV4<)4INWxMed3-8mlh+?Wjt+De<oQghL)pBK`Of<Xt7JL|>~)eYQF{C)333W6ueMk4q*cDW(QLaH>0J)S3w!R9(<L()50Z0C7K2rmpkc$wve4G%DkyTfuC62KP9}btga7A?nm<>69KT<&){NgfqQIxedQ~#=<z~^`+}d<gV^glH}flr`L2lX4y1U;>;|ko4BO58TQQ&ikJGWnp3JxHmJ5vwn4xxtAz>K9-D~1<=diGH1R(3VZ(#HtE`usvg+&^BwHk6RWkZk!9`%rl6EKLoOzq@CkR__0E3eKmfqZ38l2F2;go&@Un$3vN)|fV)F;{8@+1eBq=jw&a)T($J07+4^AU7o9ehephz!^fpv)dx)o5CUQ#)`@aVpt>XP&l~5on!z=n*=|CVijZy}uoW?fo1+b&qIiHLQb=d)YcitOMHwwzdb+S>slgQ-;R6T70<Zh*fFuX5tOp@1}1PX(_Q=ekZ5EGjxbu!PXVaZ?HlGGT5QnL6tb~1n=i^@D1}RyluuL+elni;C*U|nKaMl;x6S|6g$w<cvHw5-a$fvFSARs$4;{7$lLl6xlv=(uFX>2Gab2~wNE@&Lve~{A6r4>+<NtoZzWIs)FD#grGK(r4rL=a<~5mJe*?<3u?$B)5+U^(&AcaA9>vXm(sHqJ$C52Vn?N*+iUmH$o!q!Pv+9UkL}w7J>9?7%?ZxqKU~21FvVA7^t4E3Dgl&Um1ZB&waWeemShD?9ZhH+lG8W6t@6laTiHx)zssA~aZ2y#--}z*4e$P~^j=m*g#4fIp1is`F_l0B07Pk`rD(3`MGC?FOTM#V8^xF@)?<LzGaz)d(E0j&2$|;UsCdh^HB$TXa3KauZV`%DFvPF^A-{rWuBSk?jj{CO3Y-d2$Y?yb)lI>q|4MmpC#)Wb&*<!i$=G|KYx#0wFdo!I%wsdLH1GU&RlrOncZSI6kTCi|JWw%Y4jYil<N}^6BTUxw)REXTD)iOLI`ks7q@;pJVUj8Qcy<|&^RHtGkhpRl6+k)<vSw~KaRDEaokn{<1*A2+E-yKV~r*>rr(ciGoc{`f{N9A`xXCL%58e_QzmTQ9bn?Gw+*))EVs~6ifXGc^Urclg%R=6osP;ee5=3KJv+TKUqmew=>%x;Tl_-7b?i2oT4e~Uyz!V-CuyEa87%WRbwTzuPpx){E&cQrQg5L~oz<2f8N_Gf{kqWc}^9rIoY<h9W&LiW0&*5|!2vcn2QD_Ro0!sM)Po~(=O7hz{s*6rYzaCS3)oW=`aO79?i6TXD2n)!;FG{Ww#G`btL%AcLVPtjQ<!t!mBDm?GX`@zqZB^~Mdm+-UxydMw+kNuRr{3QIGq{ARj_K>I5n``((_$f}!#mH`@E+FjgJ@4LoF!kKWjgQ$K$5;2t^FF=@SRsxi!c-_yN~Sl~to?$niA{4NZIMg`K89&7vuaFVAU19{@wkmG5q{p~_uy>W?*-v|0E9K`N7vvp*sjYA5mtp^s!WCEO8W(I*GaUz#nqx(lKm;l&-r36u)B^gJmR7`I<&*fh+2xfMlaaAj&;(iqSkQMSN#%x3Seub$)9h@8kv1@7+B-(3kpZrI0%PD5dLT#2KFuU3dMFLy`ow{KGXH@Uvv!;9=i=Cy}D#PAnc33>L0{VcG2LmcSk%Ce%?v=AhY2LF1i;N7rC=O<3&&51J9K<lHNlU1j0%BAM{#(%6nE@|L0#H?Pf9mUktc#%7PkI%#qsH)F=GAv~@Ot^XYp>UdN8T1ZfOI;r{IdNgQt&hKx62ln2!J%xD-VF)wp`c(=)X-bK6(vIF7kA>y1PJq0|ZKaCX7$OsoUCRQyRDB4chQoJYMCM``?nC~DZ6QBb)Xx%yIO%Lk@X&b|>TAs%qE(m1vaQ1i0DTAuOPpM*y7M{P?eRHcst0h=Xa_LzvwT6E*qNVpwHw3}W>Zo<vJkP3<y-&Du9|6y|S2fKwWAc@lZamAc(%4+tz|xP!V&HYFj|QF0<`#6!w31tnb4K7YL71npEgKF$J~`(Z5*B(KULAS+xU#FsH=#DchmSdCU%xhmZV?`KWSV*~zX77;tBy3+#<(EV)-5=^`<>Zv^?7=e$+az>IV`_tWO2!JoPC`AJkYy<h8-s&$;UsdBYhoyqc=X_D_Pv5wQZ566NfDAJBhpTt;HFZ#_*wpmqEdH&ey`>;m>NIIqL$M3FVF^*OvG={P)bQ^5gJfgg0C_aeL$1v<+9$5$*sO`*HYKVBEonKSz_vYx!@b@V~OTZ~H$->U6m2c|Es8U&e*IB0G+Rmj<cu*CZacVe=)Qp+pld`GWh2_6`}|G+&S4%qUZ#%*Nb*<h&61kc_r-u2*D7IIQOd#aFY0L0(BR>(=MY;^Vo6Q`Q%#QsYAQByGy6oiTwWBzVnOv0^!~o~}vRFxj>UKWn@<O_%53vKNaTwjJ*8nP9g^)`y0HlQ1c++<xD)bn+VKa>8cm2>fQ<y1?NJZ7?cv(4mcSQ)awc;WDaP{GJ`AXMjri0<Z+!WIwk9au*)MApWVz6+e0CBG}CSKUDAn2rojo=g7n<F6VuHxe52l*25_UZ(~NNF;BR@V?BnHLS^S+w#$hL)?n!Dfj4WRlX>#Bvv{c95owjk{X4?XA^^VB0!tq(z~5$`bd=ZcUGo%(=x|rZ4dSJK$Mw;`39E#{C-w}Rwdss=_P2pF^K{Dd!^|7kj`D*b`i|zai*2~|4elwuLKw*{9f7Q!vY!wu%xi2+pu30e$y|QNaEXSfa_KQI{iw@uA4(oa_-ZFAJsd<E8GI;YoW?QFcjR8B;lMvRlPP+*-rjWv?P(a4Zy&A#oOlbU-`OAsywdWmoSvHJi+@O(>71cDj{4JTcd=9I<M{Qf^8PDI$8UJdU3-4dtrx(Tal{Frv~;rjX|-+)QBJ+@M)sgQ`;JY0Zj}|!0q%!%CG%&UVR^cTJVK|!kVE0kf&m9a9;{qP19(K6G=Zfv7+3F2Ral0b*!smn_8L6O?>MAP``Yxfxp4gihZ-BszAkvtYPDUDD%0V5hbt1N@92xNrcTXuE18ZcxL+aQ2t4t4i{fd)Q#_C-i}#1~-!T_BBxC3M5>9e9Mf4>#afI7Zj+Yq4y^o+=#j6^+Fg-aStqBS^+2NpFK%{5&zbknC)Dte&n*Ra5o@N&Cz@S0)f(u{q-!Saau>&DJ0P5|{F`s}dXXGy|NiB7L12QmA5K`@3Y4{*&Iq#3bl*-W_7xq;qzoFS*a>;aV>byUuZfDGfHprM(&h7sl(%uI_6P3g`$kj8B83XN<JdavOn*zC9<ab=lWqc+bF;<3;o-ZBq1lmbwM|auwl1bOUgIh0a;07p=JGPwn$NVXWYgxnJ5l*NX9K~ni4}3Z01h5?52eKxi@NY1;$>v~Tm(nwkJ6)VI0hnP_TCMF*U!$2{v#z#(3>5w$_dWi{avm}9QMHnH?C-t=9+AT#&o4ClDeC`{YwqEDxzlUvEw8$NPX&)=l_1SI*1vpI7X3*l>=B2T>TC2Z`pUcNvSaHXa^E9-EVoyvseW~}&a>)k{^2@e&c#f|6(Z*p*VE#zCgc8&gi=<c<<}6zdqmDkf!3RNAX&>Xn$L`eSji8h0QK>2knlyaHTo9|>&<>P|4(&}$Go;^TK4;j^k2bpl4OU1KMiq5&Y=9m=s-#I(+%hSF=$%=CrmV0ny036%KdS1#NcCIrQZnS_{0aVCJUzuKiKg)2j4;C%`c!Ng7D~>`lZFvV~L^UVA!|D3Q-p4{V|GU;qJ;JkRxcBK8@v{MBb`}qvyA|o$ANI6<N6*JIC+h+(IY&v#*NHJXqyWaQVHEKW!*fX1yA<`l859-IIXx{urg2Hyblto0<FJ-;!xRDc?6~^L$%b-~q<wkDQ28<^E2a2|@K6Ye6|(r#O*_oQn3ms7s&V=dOH)ag>@*_Qx<bt3^i~p7`<!E5x*(?2k!E1dX`<5GU|+sM14dyw1{O5D*^BE<S0%q%>12M{xk#Pb*nQSDb6}kDVT|GyF;l;bar-Se6HqE8(f;Tilf>LiFM`9V+tLS2USa^EmLkkbKJbV*K0(UIUA>dNTzb#{Qji9X>I%Xpw5Cgldvokx3Sg{g@|8vp_ABEgl0~#9oL~^<5&4<NRKx7kqAX;70b0GQStz6Ed8daWGO;i?>R&M{w>OFR?N$q>SWzQ5b%@7`5O$gaJZ3nMDw^gDp|_^T1-3a;~)h86}cg@c-!km=8YFEKB@9+TzrhsR++Erg3Nah}muiwRvDk7aUv3HMGcq^@!S5)y%x3*m2-`x?u+U1gXaq#InR}g=*2geb!k%;cLmM%e)MV5_vKOShBMIWb2IB!QE0FGC23p@3i#ijpjl%+XcBcPOWrxt{&gEoj1`a(g-Lmxbfs8YJLu6BY4Jh+nI;QIIazCZ9&-}7k(^8j@ev|jT00h$V~+1?E675PSd81N8Y;RYk%N!YH{L)_pHJTp|cy$G_*%dG2rLQAA0e7i<8@C8~d`tHZIINu6CdC21fna9zyh}Ati@51gpu_<ICl=<haG=(zW++x=amNuV(OgTfax-_jw0eF8Gq~Ek^DFFKsvqcYR4uTAWbcb-x)gGJKh%=t!MxNO9(7Id>u>l7Yj%z6l(Bp9fp>cPDs)E%I@21MX>v0TcJRHA;3F^}XExPEb#mMbd2Y7y+u4MpGq2D?QMNN%R{==}Zwn9$*OP>^>n)?3?&uF>Xheg8vDT%cd!UX)pCgOnJ4nq|+hb1XQ{f8}tA_ryCAmMy8H;){0>i_)gVHkm$Hjm2Dl?V00v?oNvcXHNF20t)XcdKQbj5&9q~i#h^6~a8$mtb>b^%#M(BfdsN`2(^YUp+tnnjfLYL~#mP#(R|TOtEb%7exd+KVcvvm#v=b2mEk?i(MX{oMpb?BF*JBSZHeZ}J>dY6V{oXVO0dv?deFoF3?Y#V?8@@Ne^&%h2`ZqDI=55)q0-V9isBAWpwCWQw2)+B5e0PMn^`C8V>XynaDc}ExtNIXp>*sS5&qx2nPj{)9=0~FK7=YuSRN1*_Aw1+KY#49xyOp#HX~!rW?5V6|dfP6}QKn>rsu{Sy+T+M!t(=X(lGj&{!HJCb{$Uk^Dd$;XT3H$3Vfbq@5dBLyl@T3-ax9GBhOsc2&uLnM)Xg|X<~WyWn#mb$HZIpB7KY#En>qJFf$$NZ6(a{dl?p7Wh7BI{BH$dO3k93(2qzQJ@k5D@5cE>c9rv10q`!paU4lHph}npLZ_ocLS_k1#tI@juB}|KUE#Mroi_-uRhP&@7K7^&gHsu_*gD~gyES4ZVO~9HI-MA)@at_`b_5ceXehB003OIz$5j+U9C*kboaspk%!oow?F^mUc2sv{22_sDu3L3d1(heiZdDg`^dUV+f&z;OT4+W3$gEEU}Y3J(C--Hi?RJ%<E6gW@4I1Pu3ar|ESA>2CR(%qAN;16Nbz>!%%l{}|B@yQ(LUudVci<ai?0BOorC3TwlMfj&)ej+R$Ax!v7xbYUS94BFD$4VQ7JvtFy>XFil2s=8!%{u=9CJaJnEX-^xTKG%Yp{m~$^)<6DMz&;%Ip|9pk?G%#Reca%GHYQUQwoI!4?ndxCBn{C{c-_;@G9~pJms&1CC*j-O=L_9+@_)A=J^e3%s*AK`PwlLKr40-ywKqNr?KT^OzJ;U)n^E(i+L&cuVy~?Z$O%CuVf``&>0A#+~OLSFB$xVsvP{((1AF?vR)s*u}J)g;<8Hs4@I)^tk6%gsZ!XMO5Er!8;E!(;FA=>k0FYLwmI6R!P{6K90c3K0b-qimIUYI33H%kw><tQOZEuh`N<c&YhQf0wAi`Do-ih`X<NcMcY#CEc#wuGV1*O=9<yypWL6Dr@x4(WJoQqDV3V%J*HeJPUBZv5(ctHn-pQ0O;$OlC>Eof_Oj5i+(L4@b!t(7imS)tH#gTEg*!TM|Z6jBO$Y;F(hu0p0hie@1*|)$i8$dWQ<p3GMv_$6m0Q5_D!aw|=A^}d4ErhtU3-Fqf;`mV=cRZbC4U2PlI<!itVeHHX7{hUHkyfSk3YI~I!~L}#rlwgZ{3tOGehS+Zj|A1=%UvCu#&n15$s5ETZ+1bMF$dL>c5nNXn9A=7ZVo+0FM%7bxefL5;h}3%yJQJk+Dm*t?3e9@Z7*gUv#Ycq4{w8uEt*k&8eIt6PB(&g91SS8TDg&c7(W%_BD<9d*#zmP*lgY(joqa-9xfHd6M0~<?>7P=5?`)#Ca^f!vQQl*d}O{UI52bD#e6jF$3qjU3IEj8jS;RNZ@6ewYSb-09>=37{2ln9m+(mY`UI44YvA!SJ&xjYA7sNLZn7}=l0V*4_~fLYlIjdv420g4pap=^lui5c{w`EwY6n-1<5sEik$7x#%v?H6Ttwk;_Pq>l<jjEJsvrK^h7E2rS8kgVuo_;x|5-91B+yv01s>wG9NzLpBcAuP7~JX-G2Hu3*~P4iE5ZnD9HuNCZ&PGqD_xq7mt-f_*PtAx;{IBBUnxQIU+q6$`g9T(Mw;agU!`9zdwPMN<2WT#dJ5x4<%pjlqgHC!F(`v1B_j7}DaDl={U`}o$@pG8XPz>;@?r_@dh|nBqqE!0+DcjIo9Vb|w(4CH2N~)y-~*9xP)UrpH;5y77l|YBMv#o4oLsOVSnr2?Rf;Y$T45d-XfC|BIEY939?6qbK*Tk`6FOBvIV?p8@5)si-Wf!t=J(yz#+SY95o@um(Dzrzq>sR4-1ZVre=g5iZb^}e(92tVJOB~V&3P?Nf%UdclJcOE@pW8ek{8)0I1i|{tx(}p5mtpRk{gAeCo%(b=N>BjdLm&Fj*Q4-8*X+1BAz~;`GYND38y_F6kgQEb3DpAgSROaNb%5YY~O}p5f@V;LiW;uis~xfH3=Fvv$kd|pB#dDpYCz1#%^TK&h?atnmbzDj{TO%$UXqdAP9Vk*jU61B8%a$pGfP>I%6D($aFjNy<@IjXptIc9*?~U52O$hlyl<I|MCB<Oz2N#Vt!*oz>7bOh*~}7a)X0Pb0sq%B(;lR!&#KcLr{^>*FNvKS*{7od>#KqqsYKHlA}<{`;!-Ez=~vC3(>O2Lry@;+~7nSS0y5^un+i_B17oDsZ~%Z8!4)x01e+3oYz!?ICap(dL(@5QNqfzv6BA{j7FjgvD(5wIpKZwi*AAYEG<-NZzGo-KU$pE-SNY>c~Ya+O4;EMJ_k$RHN$;kAw0foD-8DO9N4Zf`bEKzw$3drz8GgcBENOx(YOJ;-DplU3O~{469dj7yNd9HuQFIRox)EHO8lZ_<k>BzHjqh9Pm-_Q{5)i@^~2Aaw=;vNF=`<k53S(OYMStN40!&oYDZkXl=*5YG%`(>`yI{z!C56znPERkd-2v2))Lz_7QC5D0D`u&4DddzA-q0@e$lr_V;!P1-5Glvxi|n!>E8nw9lziIFF9|MTm"
)


class GscVideoRecoveryError(RuntimeError):
    pass


@dataclass(frozen=True)
class RecoveryDeadline:
    expires_at: float

    @classmethod
    def start(cls, timeout_seconds: float) -> "RecoveryDeadline":
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise GscVideoRecoveryError(
                "Video recovery requires a positive finite shared deadline."
            )
        return cls(time.monotonic() + float(timeout_seconds))

    def remaining(self, context: str) -> float:
        remaining = self.expires_at - time.monotonic()
        if remaining <= 0:
            raise GscVideoRecoveryError(
                f"Video recovery exhausted its shared deadline while {context}."
            )
        return remaining

    def check(self, context: str) -> None:
        self.remaining(context)


@dataclass(frozen=True)
class FrameWindow:
    start_frame: int
    end_frame: int
    authority: str

    def __post_init__(self) -> None:
        if (
            isinstance(self.start_frame, bool)
            or isinstance(self.end_frame, bool)
            or self.start_frame < 0
            or self.end_frame <= self.start_frame
        ):
            raise GscVideoRecoveryError(
                f"Invalid half-open frame window [{self.start_frame}, {self.end_frame})."
            )
        if not str(self.authority).strip():
            raise GscVideoRecoveryError("Calibration window lacks authority evidence.")


@dataclass(frozen=True)
class GrayWindowGeometry:
    """A fixed spatial crop normalized to a fixed grayscale sample size."""

    crop_x: int
    crop_y: int
    crop_width: int
    crop_height: int
    sample_width: int
    sample_height: int

    def __post_init__(self) -> None:
        values = (
            self.crop_x,
            self.crop_y,
            self.crop_width,
            self.crop_height,
            self.sample_width,
            self.sample_height,
        )
        if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
            raise GscVideoRecoveryError("Gray-window geometry requires integer dimensions.")
        if self.crop_x < 0 or self.crop_y < 0:
            raise GscVideoRecoveryError("Gray-window crop origin cannot be negative.")
        if min(
            self.crop_width,
            self.crop_height,
            self.sample_width,
            self.sample_height,
        ) <= 0:
            raise GscVideoRecoveryError("Gray-window dimensions must be positive.")

    @property
    def frame_bytes(self) -> int:
        return self.sample_width * self.sample_height


HEADER_TITLE_GEOMETRY = GrayWindowGeometry(
    crop_x=HEADER_TITLE_X,
    crop_y=HEADER_TITLE_Y,
    crop_width=HEADER_TITLE_WIDTH,
    crop_height=HEADER_TITLE_HEIGHT,
    sample_width=HEADER_TITLE_WIDTH,
    sample_height=HEADER_TITLE_HEIGHT,
)

RawWindowExtractor = Callable[
    [Path, Sequence[int], RecoveryDeadline], Mapping[int, bytes]
]


@dataclass(frozen=True)
class ModeCalibration:
    overworld_template: bytes
    battle_template: bytes
    overworld_window: FrameWindow
    battle_window: FrameWindow
    template_separation: float
    acceptance_radius: float
    minimum_margin: float
    overworld_max_within_distance: float
    battle_max_within_distance: float
    evidence_sha256: str


@dataclass(frozen=True)
class RawStateRun:
    ordinal: int
    state: str
    start_frame: int
    end_frame: int
    minimum_winner_distance: float
    maximum_winner_distance: float
    minimum_margin: float

    @property
    def frame_count(self) -> int:
        return self.end_frame - self.start_frame


@dataclass(frozen=True)
class ResolvedBattleRun:
    ordinal: int
    start_frame: int
    end_frame: int
    source_raw_run_ordinals: tuple[int, ...]
    identity_probe_frame: int


@dataclass(frozen=True)
class FixedHeaderSemanticEvidence:
    """Closed, receipt-owned evidence for one raw Battle-state run.

    ``title_template_sha256`` is the stable key of the deterministic fixed
    header-title template selected for the run.  The attempt fields bind the
    declared integer to the independently selected finite attempt template.
    No field is free-form transcript or OCR output.
    """

    raw_run_ordinal: int
    probe_frame: int
    title_template_sha256: str
    title_evidence_sha256: str
    title_normalized_distance: float
    title_runner_up_distance: float
    attempt: int
    matched_attempt: int
    attempt_template_sha256: str
    attempt_evidence_sha256: str
    attempt_normalized_distance: float
    attempt_runner_up_distance: float


@dataclass(frozen=True)
class DiscardedRawBattleRun:
    raw_run_ordinal: int
    reason_code: str
    evidence: str


@dataclass(frozen=True)
class RunResolution:
    policy_id: str
    raw_runs_sha256: str
    battles: tuple[ResolvedBattleRun, ...]
    fixed_header_semantics: tuple[FixedHeaderSemanticEvidence, ...] = ()
    discarded_battle_runs: tuple[DiscardedRawBattleRun, ...] = ()


@dataclass(frozen=True)
class ProjectionAnchor:
    vertical_frame: int
    main_frame: int
    normalized_distance: float
    runner_up_distance: float
    vertical_window_sha256: str
    main_window_sha256: str
    method: str = PROJECTION_METHOD


@dataclass(frozen=True)
class ProjectionProof:
    expected_offset_frames: int
    residual_tolerance_frames: int
    anchors: tuple[ProjectionAnchor, ...]
    evidence_sha256: str


@dataclass(frozen=True)
class IdentityMatch:
    display_text: str
    identity: str
    role: str
    trainer_class: str
    trainer_id: int | None
    normalized_distance: float
    runner_up_distance: float
    evidence_sha256: str


def _read_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GscVideoRecoveryError(f"Could not read {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise GscVideoRecoveryError(f"{label} must be a JSON object: {path}")
    return value


def _same_path(left: Any, right: Path) -> bool:
    if not str(left or "").strip():
        return False
    try:
        left_path = Path(str(left)).resolve()
        right_path = right.resolve()
    except (OSError, ValueError):
        return False
    return os.path.normcase(str(left_path)) == os.path.normcase(str(right_path))


def _sha256_file(path: Path, deadline: RecoveryDeadline) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            deadline.check(f"hashing finalized vertical capture {path.name}")
            chunk = stream.read(8 * 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest().lower()


def validate_finalized_vertical_linkage(
    meta_path: Path,
    *,
    deadline: RecoveryDeadline,
    events_path: Path | None = None,
    verify_sha256: bool = True,
) -> dict[str, Any]:
    """Validate the exact finalized vertical WebM/manifest/session linkage."""

    meta_path = meta_path.resolve()
    if not meta_path.is_file():
        raise GscVideoRecoveryError(f"Missing canonical session metadata: {meta_path}")
    meta = _read_json_object(meta_path, "canonical session metadata")
    vertical = meta.get("verticalRecording")
    if not isinstance(vertical, dict) or vertical.get("status") != "finalized":
        raise GscVideoRecoveryError("Vertical recording is not finalized in meta.json.")

    manifest_path = Path(str(vertical.get("manifestPath") or "")).resolve()
    capture_path = Path(str(vertical.get("filePath") or "")).resolve()
    if not manifest_path.is_file():
        raise GscVideoRecoveryError(f"Missing linked vertical manifest: {manifest_path}")
    if (
        not capture_path.is_file()
        or capture_path.stat().st_size <= 0
        or capture_path.name.casefold().endswith(".partial.webm")
        or capture_path.suffix.casefold() != ".webm"
    ):
        raise GscVideoRecoveryError(f"Missing finalized vertical WebM: {capture_path}")

    manifest = _read_json_object(manifest_path, "vertical recording manifest")
    if manifest.get("schema") != VERTICAL_MANIFEST_SCHEMA:
        raise GscVideoRecoveryError("Unsupported vertical recording manifest schema.")
    if manifest.get("status") != "finalized":
        raise GscVideoRecoveryError("Vertical manifest is not finalized.")
    output = manifest.get("output")
    if not isinstance(output, dict) or output.get("finalized") is not True:
        raise GscVideoRecoveryError("Vertical manifest output is not finalized.")
    if output.get("fileName") != capture_path.name:
        raise GscVideoRecoveryError("Vertical manifest output filename disagrees with meta.json.")
    if ".partial." in str(output.get("fileName") or "").casefold():
        raise GscVideoRecoveryError("Vertical manifest still names a partial capture.")

    canvas = manifest.get("canvas")
    if not isinstance(canvas, dict) or (
        canvas.get("width"), canvas.get("height"), canvas.get("frameRate")
    ) != (VERTICAL_WIDTH, VERTICAL_HEIGHT, FPS):
        raise GscVideoRecoveryError(
            "Vertical manifest must declare the exact 1080x1920p60 canvas."
        )
    codec = manifest.get("codec")
    if not isinstance(codec, dict) or codec.get("container") != "webm":
        raise GscVideoRecoveryError("Vertical manifest does not declare a WebM capture.")

    manifest_session = manifest.get("session")
    if not isinstance(manifest_session, dict):
        raise GscVideoRecoveryError("Vertical manifest lacks session correlation.")
    expected_session_id = meta_path.parent.name
    for key in ("recordingId", "segmentId"):
        if str(manifest_session.get(key) or "") != str(vertical.get(key) or ""):
            raise GscVideoRecoveryError(
                f"Vertical manifest/meta {key} correlation is inconsistent."
            )
    if str(manifest_session.get("id") or "") != expected_session_id:
        raise GscVideoRecoveryError("Vertical manifest session ID disagrees with the log folder.")

    correlation = manifest.get("correlation")
    linked = correlation.get("linkedLogRefs") if isinstance(correlation, dict) else None
    if not isinstance(linked, dict):
        raise GscVideoRecoveryError("Vertical manifest lacks linked log references.")
    if str(linked.get("sessionId") or "") != expected_session_id:
        raise GscVideoRecoveryError("Vertical manifest linked-log session ID is inconsistent.")
    if not _same_path(linked.get("metaPath"), meta_path):
        raise GscVideoRecoveryError("Vertical manifest is not linked to this meta.json.")
    if events_path is not None and not _same_path(linked.get("eventsPath"), events_path):
        raise GscVideoRecoveryError("Vertical manifest is not linked to the supplied events.json.")

    stat_before = capture_path.stat()
    declared_bytes = manifest.get("bytes")
    if isinstance(declared_bytes, bool) or int(declared_bytes or 0) != stat_before.st_size:
        raise GscVideoRecoveryError("Vertical manifest byte count is stale.")
    declared_sha = str(manifest.get("sha256") or "").lower()
    if not re.fullmatch(r"[0-9a-f]{64}", declared_sha):
        raise GscVideoRecoveryError("Vertical manifest lacks a valid SHA-256 receipt.")
    actual_sha = declared_sha
    if verify_sha256:
        actual_sha = _sha256_file(capture_path, deadline)
        if actual_sha != declared_sha:
            raise GscVideoRecoveryError("Vertical capture SHA-256 does not match its manifest.")
    stat_after = capture_path.stat()
    if (stat_before.st_size, stat_before.st_mtime_ns) != (
        stat_after.st_size,
        stat_after.st_mtime_ns,
    ):
        raise GscVideoRecoveryError("Vertical capture changed during linkage validation.")

    duration_ms = manifest.get("durationMs")
    if (
        isinstance(duration_ms, bool)
        or not isinstance(duration_ms, (int, float))
        or duration_ms <= 0
    ):
        raise GscVideoRecoveryError("Vertical manifest lacks a positive durationMs.")
    declared_frames = round(float(duration_ms) * FPS / 1000.0)
    return {
        "schema": "gsc_finalized_vertical_linkage_v1",
        "status": "pass",
        "meta_path": str(meta_path),
        "manifest_path": str(manifest_path),
        "capture_path": str(capture_path),
        "session_id": expected_session_id,
        "recording_id": str(vertical.get("recordingId") or ""),
        "segment_id": str(vertical.get("segmentId") or ""),
        "bytes": stat_after.st_size,
        "sha256": actual_sha,
        "sha256_verified": verify_sha256,
        "duration_ms": float(duration_ms),
        "declared_frames_at_60fps": declared_frames,
        "canvas": {"width": VERTICAL_WIDTH, "height": VERTICAL_HEIGHT, "fps": FPS},
        "mode_chip": {
            "x": MODE_CHIP_X,
            "y": MODE_CHIP_Y,
            "width": MODE_CHIP_WIDTH,
            "height": MODE_CHIP_HEIGHT,
        },
    }


def _normalized_sad(left: bytes, right: bytes) -> float:
    if len(left) != len(right) or not left:
        raise GscVideoRecoveryError("Pixel samples have inconsistent dimensions.")
    return sum(abs(a - b) for a, b in zip(left, right)) / (255.0 * len(left))


def _median_template(samples: Sequence[bytes]) -> bytes:
    if not samples or any(len(row) != MODE_SAMPLE_BYTES for row in samples):
        raise GscVideoRecoveryError("Mode calibration samples have invalid dimensions.")
    ordered_columns = [sorted(row[index] for row in samples) for index in range(MODE_SAMPLE_BYTES)]
    middle = (len(samples) - 1) // 2
    return bytes(column[middle] for column in ordered_columns)


def calibrate_mode_templates(
    frame_samples: Mapping[int, bytes],
    *,
    overworld_window: FrameWindow,
    battle_window: FrameWindow,
) -> ModeCalibration:
    """Self-calibrate chip templates from authoritative pre-truncation windows."""

    if overworld_window.end_frame > battle_window.start_frame and (
        battle_window.end_frame > overworld_window.start_frame
    ):
        raise GscVideoRecoveryError("Battle and Overworld calibration windows overlap.")
    overworld = [
        frame_samples[frame]
        for frame in range(overworld_window.start_frame, overworld_window.end_frame)
        if frame in frame_samples
    ]
    battle = [
        frame_samples[frame]
        for frame in range(battle_window.start_frame, battle_window.end_frame)
        if frame in frame_samples
    ]
    if len(overworld) < 3 or len(battle) < 3:
        raise GscVideoRecoveryError(
            "Each authoritative mode calibration window requires at least three decoded frames."
        )
    overworld_template = _median_template(overworld)
    battle_template = _median_template(battle)
    separation = _normalized_sad(overworld_template, battle_template)
    if separation < 0.015:
        raise GscVideoRecoveryError(
            "Authoritative Battle/Overworld chip templates are not separable."
        )
    overworld_within = max(_normalized_sad(row, overworld_template) for row in overworld)
    battle_within = max(_normalized_sad(row, battle_template) for row in battle)
    worst_within = max(overworld_within, battle_within)
    if worst_within >= separation * 0.45:
        raise GscVideoRecoveryError(
            "Authoritative mode windows are unstable relative to their separation."
        )
    acceptance_radius = min(separation * 0.45, max(0.002, worst_within * 3.0 + 0.001))
    minimum_margin = max(0.002, separation * 0.20)
    evidence = {
        "overworld_window": overworld_window.__dict__,
        "battle_window": battle_window.__dict__,
        "overworld_template_sha256": hashlib.sha256(overworld_template).hexdigest(),
        "battle_template_sha256": hashlib.sha256(battle_template).hexdigest(),
        "separation": separation,
        "acceptance_radius": acceptance_radius,
        "minimum_margin": minimum_margin,
        "overworld_samples": len(overworld),
        "battle_samples": len(battle),
    }
    return ModeCalibration(
        overworld_template=overworld_template,
        battle_template=battle_template,
        overworld_window=overworld_window,
        battle_window=battle_window,
        template_separation=separation,
        acceptance_radius=acceptance_radius,
        minimum_margin=minimum_margin,
        overworld_max_within_distance=overworld_within,
        battle_max_within_distance=battle_within,
        evidence_sha256=hashlib.sha256(
            json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
    )


def classify_mode_sample(sample: bytes, calibration: ModeCalibration) -> tuple[str, float, float]:
    if len(sample) != MODE_SAMPLE_BYTES:
        raise GscVideoRecoveryError("Mode chip sample has invalid dimensions.")
    distances = {
        "overworld": _normalized_sad(sample, calibration.overworld_template),
        "battle": _normalized_sad(sample, calibration.battle_template),
    }
    ordered = sorted(distances.items(), key=lambda item: (item[1], item[0]))
    winner, winner_distance = ordered[0]
    margin = ordered[1][1] - winner_distance
    if (
        winner_distance > calibration.acceptance_radius
        or margin < calibration.minimum_margin
    ):
        return "unknown", winner_distance, margin
    return winner, winner_distance, margin


def raw_runs_from_samples(
    frame_samples: Iterable[tuple[int, bytes]],
    *,
    calibration: ModeCalibration,
) -> tuple[RawStateRun, ...]:
    runs: list[RawStateRun] = []
    active_state: str | None = None
    start = -1
    previous = -1
    distances: list[float] = []
    margins: list[float] = []

    def close(end_frame: int) -> None:
        nonlocal active_state, start, distances, margins
        if active_state is None:
            return
        runs.append(
            RawStateRun(
                ordinal=len(runs) + 1,
                state=active_state,
                start_frame=start,
                end_frame=end_frame,
                minimum_winner_distance=min(distances),
                maximum_winner_distance=max(distances),
                minimum_margin=min(margins),
            )
        )
        active_state = None
        distances = []
        margins = []

    for frame, sample in frame_samples:
        if isinstance(frame, bool) or frame < 0 or (previous >= 0 and frame != previous + 1):
            raise GscVideoRecoveryError("Mode chip frame stream is not exactly contiguous at 60fps.")
        state, distance, margin = classify_mode_sample(sample, calibration)
        if state != active_state:
            if active_state is not None:
                close(frame)
            active_state = state
            start = frame
        distances.append(distance)
        margins.append(margin)
        previous = frame
    if active_state is not None:
        close(previous + 1)
    return tuple(runs)


def _normalized_probe_frames(probe_frames: Sequence[int]) -> tuple[int, ...]:
    supplied = tuple(probe_frames)
    if not supplied:
        raise GscVideoRecoveryError("At least one probe frame is required.")
    if any(
        isinstance(frame, bool) or not isinstance(frame, int) or frame < 0
        for frame in supplied
    ):
        raise GscVideoRecoveryError("Probe frame numbers must be non-negative integers.")
    ordered = tuple(sorted(supplied))
    if len(set(ordered)) != len(ordered):
        raise GscVideoRecoveryError("Probe frame numbers must be unique.")
    return ordered


def fixed_gray_probe_ffmpeg_command(
    capture_path: Path,
    *,
    probe_frames: Sequence[int],
    geometry: GrayWindowGeometry,
    ffmpeg: str = "ffmpeg",
) -> list[str]:
    """Build a no-seek exact-60fps sparse fixed-window extraction command."""

    ordered = _normalized_probe_frames(probe_frames)
    select_expression = "+".join(f"eq(n\\,{frame})" for frame in ordered)
    filters = [
        "fps=fps=60:round=near",
        f"select={select_expression}",
        (
            f"crop={geometry.crop_width}:{geometry.crop_height}:"
            f"{geometry.crop_x}:{geometry.crop_y}"
        ),
    ]
    if (
        geometry.crop_width != geometry.sample_width
        or geometry.crop_height != geometry.sample_height
    ):
        filters.append(
            f"scale={geometry.sample_width}:{geometry.sample_height}:flags=area"
        )
    filters.append("format=gray")
    return [
        ffmpeg,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(capture_path.resolve()),
        "-map",
        "0:v:0",
        "-an",
        "-vf",
        ",".join(filters),
        "-frames:v",
        str(len(ordered)),
        "-fps_mode",
        "passthrough",
        "-f",
        "rawvideo",
        "pipe:1",
    ]


def header_title_ffmpeg_command(
    capture_path: Path,
    *,
    probe_frames: Sequence[int],
    ffmpeg: str = "ffmpeg",
) -> list[str]:
    """Build the fixed GSC vertical header-title grayscale extraction command."""

    return fixed_gray_probe_ffmpeg_command(
        capture_path,
        probe_frames=probe_frames,
        geometry=HEADER_TITLE_GEOMETRY,
        ffmpeg=ffmpeg,
    )


def mode_scan_ffmpeg_command(
    capture_path: Path,
    *,
    end_frame: int,
    ffmpeg: str = "ffmpeg",
) -> list[str]:
    if isinstance(end_frame, bool) or end_frame <= 0:
        raise GscVideoRecoveryError("Mode scan end frame must be positive.")
    return [
        ffmpeg,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(capture_path.resolve()),
        "-map",
        "0:v:0",
        "-an",
        "-vf",
        (
            "fps=fps=60:round=near,"
            f"crop={MODE_CHIP_WIDTH}:{MODE_CHIP_HEIGHT}:{MODE_CHIP_X}:{MODE_CHIP_Y},"
            f"scale={MODE_SAMPLE_WIDTH}:{MODE_SAMPLE_HEIGHT}:flags=area,format=gray"
        ),
        "-frames:v",
        str(end_frame),
        "-fps_mode",
        "passthrough",
        "-f",
        "rawvideo",
        "pipe:1",
    ]


def _terminate_owned_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.kill()
    try:
        process.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        pass


def _stream_fixed_frames(
    command: Sequence[str],
    *,
    frame_bytes: int,
    expected_frames: int,
    deadline: RecoveryDeadline,
    context: str = "the exact 60fps vertical mode scan",
) -> Iterable[tuple[int, bytes]]:
    """Yield fixed-size raw frames without allowing a blocking pipe to outrun the deadline."""

    if frame_bytes <= 0 or expected_frames <= 0:
        raise GscVideoRecoveryError("Streaming frame dimensions must be positive.")
    try:
        process = subprocess.Popen(
            list(command),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        raise GscVideoRecoveryError(f"Could not start ffmpeg: {exc}") from exc
    assert process.stdout is not None
    assert process.stderr is not None
    output_queue: queue.Queue[bytes | BaseException | None] = queue.Queue(maxsize=128)
    stderr_chunks: list[bytes] = []

    def read_stdout() -> None:
        try:
            buffer = bytearray()
            while True:
                chunk = process.stdout.read(64 * 1024)
                if not chunk:
                    break
                buffer.extend(chunk)
                while len(buffer) >= frame_bytes:
                    payload = bytes(buffer[:frame_bytes])
                    del buffer[:frame_bytes]
                    output_queue.put(payload)
            if buffer:
                output_queue.put(
                    GscVideoRecoveryError(
                        f"ffmpeg ended with {len(buffer)} trailing rawvideo bytes."
                    )
                )
        except BaseException as exc:  # forwarded to the deadline-owning thread
            output_queue.put(exc)
        finally:
            output_queue.put(None)

    def read_stderr() -> None:
        while True:
            chunk = process.stderr.read(16 * 1024)
            if not chunk:
                return
            if sum(len(row) for row in stderr_chunks) < 256 * 1024:
                stderr_chunks.append(chunk)

    stdout_thread = threading.Thread(target=read_stdout, daemon=True)
    stderr_thread = threading.Thread(target=read_stderr, daemon=True)
    stdout_thread.start()
    stderr_thread.start()
    yielded = 0
    try:
        while True:
            remaining = deadline.remaining(f"streaming {context}")
            try:
                item = output_queue.get(timeout=min(0.25, remaining))
            except queue.Empty:
                continue
            if item is None:
                break
            if isinstance(item, BaseException):
                raise GscVideoRecoveryError(f"ffmpeg rawvideo reader failed: {item}") from item
            if yielded >= expected_frames:
                raise GscVideoRecoveryError("ffmpeg emitted more mode frames than requested.")
            yield yielded, item
            yielded += 1
        try:
            return_code = process.wait(
                timeout=deadline.remaining(f"waiting for {context} to exit")
            )
        except subprocess.TimeoutExpired as exc:
            raise GscVideoRecoveryError(
                f"ffmpeg exceeded the shared deadline while running {context}."
            ) from exc
        if return_code != 0:
            detail = b"".join(stderr_chunks).decode("utf-8", errors="replace").strip()
            raise GscVideoRecoveryError(
                f"ffmpeg {context} failed with status {return_code}: {detail}"
            )
        if yielded != expected_frames:
            raise GscVideoRecoveryError(
                f"ffmpeg decoded {yielded}/{expected_frames} frames for {context}."
            )
    finally:
        _terminate_owned_process(process)


def extract_fixed_gray_probe_frames(
    capture_path: Path,
    *,
    probe_frames: Sequence[int],
    geometry: GrayWindowGeometry,
    deadline: RecoveryDeadline,
    ffmpeg: str = "ffmpeg",
) -> dict[int, bytes]:
    """Extract sparse fixed grayscale windows without escaping the shared deadline."""

    capture_path = capture_path.resolve()
    if not capture_path.is_file() or capture_path.stat().st_size <= 0:
        raise GscVideoRecoveryError(f"Missing capture for gray-window extraction: {capture_path}")
    ordered = _normalized_probe_frames(probe_frames)
    command = fixed_gray_probe_ffmpeg_command(
        capture_path,
        probe_frames=ordered,
        geometry=geometry,
        ffmpeg=ffmpeg,
    )
    samples: list[bytes] = []
    for _ordinal, sample in _stream_fixed_frames(
        command,
        frame_bytes=geometry.frame_bytes,
        expected_frames=len(ordered),
        deadline=deadline,
        context="the exact 60fps fixed gray-window probe",
    ):
        samples.append(sample)
    return dict(zip(ordered, samples))


def extract_header_title_frames(
    capture_path: Path,
    *,
    probe_frames: Sequence[int],
    deadline: RecoveryDeadline,
    ffmpeg: str = "ffmpeg",
) -> dict[int, bytes]:
    """Extract exact fixed GSC header-title crops for finite-atlas matching."""

    return extract_fixed_gray_probe_frames(
        capture_path,
        probe_frames=probe_frames,
        geometry=HEADER_TITLE_GEOMETRY,
        deadline=deadline,
        ffmpeg=ffmpeg,
    )


def scan_vertical_mode_runs(
    capture_path: Path,
    *,
    overworld_window: FrameWindow,
    battle_window: FrameWindow,
    recovery_start_frame: int,
    scan_end_frame: int,
    deadline: RecoveryDeadline,
    ffmpeg: str = "ffmpeg",
) -> dict[str, Any]:
    """Run one bounded, streaming 60fps scan and expose unfiltered raw runs."""

    capture_path = capture_path.resolve()
    if not capture_path.is_file() or capture_path.stat().st_size <= 0:
        raise GscVideoRecoveryError(f"Missing finalized vertical capture: {capture_path}")
    if (
        isinstance(recovery_start_frame, bool)
        or not isinstance(recovery_start_frame, int)
        or recovery_start_frame < 0
    ):
        raise GscVideoRecoveryError(
            "Recovery start frame must be a non-negative integer."
        )
    if (
        isinstance(scan_end_frame, bool)
        or not isinstance(scan_end_frame, int)
        or scan_end_frame <= 0
    ):
        raise GscVideoRecoveryError("Video recovery scan end frame must be positive.")
    if scan_end_frame <= recovery_start_frame:
        raise GscVideoRecoveryError("Video recovery scan range is empty.")
    calibration_end = max(overworld_window.end_frame, battle_window.end_frame)
    if calibration_end > scan_end_frame:
        raise GscVideoRecoveryError(
            "Both authoritative calibration windows must be contained in the decoded scan."
        )
    command = mode_scan_ffmpeg_command(capture_path, end_frame=scan_end_frame, ffmpeg=ffmpeg)
    calibration_samples: dict[int, bytes] = {}
    recovery_samples: list[tuple[int, bytes]] = []
    for frame, sample in _stream_fixed_frames(
        command,
        frame_bytes=MODE_SAMPLE_BYTES,
        expected_frames=scan_end_frame,
        deadline=deadline,
    ):
        if (
            overworld_window.start_frame <= frame < overworld_window.end_frame
            or battle_window.start_frame <= frame < battle_window.end_frame
        ):
            calibration_samples[frame] = sample
        if frame >= recovery_start_frame:
            recovery_samples.append((frame, sample))
    calibration = calibrate_mode_templates(
        calibration_samples,
        overworld_window=overworld_window,
        battle_window=battle_window,
    )
    runs = raw_runs_from_samples(recovery_samples, calibration=calibration)
    rows = [
        {
            "ordinal": row.ordinal,
            "state": row.state,
            "start_frame": row.start_frame,
            "end_frame": row.end_frame,
            "frame_count": row.frame_count,
            "minimum_winner_distance": row.minimum_winner_distance,
            "maximum_winner_distance": row.maximum_winner_distance,
            "minimum_margin": row.minimum_margin,
        }
        for row in runs
    ]
    raw_digest = raw_runs_sha256(runs)
    return {
        "schema": RAW_RUN_SCHEMA,
        "status": "raw_evidence_only",
        "capture_path": str(capture_path),
        "fps": FPS,
        "scan_start_frame": recovery_start_frame,
        "scan_end_frame": scan_end_frame,
        "calibration": {
            "overworld_window": overworld_window.__dict__,
            "battle_window": battle_window.__dict__,
            "template_separation": calibration.template_separation,
            "acceptance_radius": calibration.acceptance_radius,
            "minimum_margin": calibration.minimum_margin,
            "evidence_sha256": calibration.evidence_sha256,
        },
        "fixed_chip": {
            "x": MODE_CHIP_X,
            "y": MODE_CHIP_Y,
            "width": MODE_CHIP_WIDTH,
            "height": MODE_CHIP_HEIGHT,
            "sample_width": MODE_SAMPLE_WIDTH,
            "sample_height": MODE_SAMPLE_HEIGHT,
        },
        "raw_runs": rows,
        "raw_runs_sha256": raw_digest,
        "run_resolution_required": True,
        "bounce_filter": None,
    }


def raw_runs_sha256(runs: Sequence[RawStateRun]) -> str:
    payload = [
        {
            "ordinal": row.ordinal,
            "state": row.state,
            "start_frame": row.start_frame,
            "end_frame": row.end_frame,
            "minimum_winner_distance": row.minimum_winner_distance,
            "maximum_winner_distance": row.maximum_winner_distance,
            "minimum_margin": row.minimum_margin,
        }
        for row in runs
    ]
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def fixed_header_semantics_sha256(
    semantics: Sequence[FixedHeaderSemanticEvidence],
) -> str:
    payload = [row.__dict__ for row in semantics]
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _semantic_battle_groups(
    raw_runs: Sequence[RawStateRun],
    semantics: Sequence[FixedHeaderSemanticEvidence],
) -> tuple[tuple[RawStateRun, ...], ...]:
    """Return exact physical attempts from fixed title+attempt evidence.

    A temporary mode-chip exit after a party member faints does not end the
    physical battle.  Consecutive raw Battle runs with the same fixed title
    template and the same evidenced attempt therefore remain one range.  A
    changed, sequential attempt value starts a retry; a changed title starts a
    different encounter.
    """

    battle_rows = tuple(row for row in raw_runs if row.state == "battle")
    by_ordinal = {row.ordinal: row for row in battle_rows}
    supplied = tuple(semantics)
    if len(supplied) != len(battle_rows):
        raise GscVideoRecoveryError(
            "Every raw Battle run requires exactly one fixed-header semantic evidence row."
        )

    expected_ordinals = {row.ordinal for row in battle_rows}
    seen_ordinals: set[int] = set()
    attempt_template_by_value: dict[int, str] = {}
    attempt_value_by_template: dict[str, int] = {}
    ordered_semantics: list[FixedHeaderSemanticEvidence] = []
    for evidence in supplied:
        raw_ordinal = evidence.raw_run_ordinal
        if (
            isinstance(raw_ordinal, bool)
            or not isinstance(raw_ordinal, int)
            or raw_ordinal not in expected_ordinals
            or raw_ordinal in seen_ordinals
        ):
            raise GscVideoRecoveryError(
                "Fixed-header semantic evidence has a missing, non-Battle, or duplicate raw-run ordinal."
            )
        seen_ordinals.add(raw_ordinal)
        raw = by_ordinal[raw_ordinal]
        if (
            isinstance(evidence.probe_frame, bool)
            or not isinstance(evidence.probe_frame, int)
            or not raw.start_frame <= evidence.probe_frame < raw.end_frame
        ):
            raise GscVideoRecoveryError(
                f"Fixed-header semantic probe for raw run {raw_ordinal} lies outside its source range."
            )
        digests = (
            evidence.title_template_sha256,
            evidence.title_evidence_sha256,
            evidence.attempt_template_sha256,
            evidence.attempt_evidence_sha256,
        )
        if any(re.fullmatch(r"[0-9a-fA-F]{64}", str(value or "")) is None for value in digests):
            raise GscVideoRecoveryError(
                f"Fixed-header semantic evidence for raw run {raw_ordinal} lacks full SHA-256 binding."
            )
        if (
            isinstance(evidence.attempt, bool)
            or not isinstance(evidence.attempt, int)
            or evidence.attempt <= 0
            or isinstance(evidence.matched_attempt, bool)
            or not isinstance(evidence.matched_attempt, int)
            or evidence.matched_attempt <= 0
        ):
            raise GscVideoRecoveryError(
                f"Fixed-header attempt evidence for raw run {raw_ordinal} must be positive integers."
            )
        if evidence.attempt != evidence.matched_attempt:
            raise GscVideoRecoveryError(
                "Declared fixed-header attempt does not match its finite-template evidence: "
                f"raw run {raw_ordinal} declares {evidence.attempt}, matched "
                f"{evidence.matched_attempt}."
            )
        score_pairs = (
            (
                evidence.title_normalized_distance,
                evidence.title_runner_up_distance,
                "title",
            ),
            (
                evidence.attempt_normalized_distance,
                evidence.attempt_runner_up_distance,
                "attempt",
            ),
        )
        for distance, runner_up, label in score_pairs:
            if (
                not math.isfinite(distance)
                or not math.isfinite(runner_up)
                or distance < 0
                or runner_up < distance
                or distance > MAX_FIXED_HEADER_SEMANTIC_DISTANCE
                or runner_up - distance < MIN_FIXED_HEADER_SEMANTIC_MARGIN
            ):
                raise GscVideoRecoveryError(
                    f"Fixed-header {label} evidence for raw run {raw_ordinal} is weak or ambiguous."
                )

        template_key = evidence.attempt_template_sha256.lower()
        previous_template = attempt_template_by_value.setdefault(
            evidence.matched_attempt, template_key
        )
        previous_value = attempt_value_by_template.setdefault(
            template_key, evidence.matched_attempt
        )
        if previous_template != template_key or previous_value != evidence.matched_attempt:
            raise GscVideoRecoveryError(
                "Finite attempt-template evidence is not one-to-one with its matched integer."
            )
        ordered_semantics.append(evidence)

    if seen_ordinals != expected_ordinals:
        raise GscVideoRecoveryError(
            "Fixed-header semantic evidence does not cover every raw Battle run."
        )
    ordered_semantics.sort(key=lambda row: by_ordinal[row.raw_run_ordinal].start_frame)

    groups: list[list[RawStateRun]] = []
    previous_evidence: FixedHeaderSemanticEvidence | None = None
    for evidence in ordered_semantics:
        raw = by_ordinal[evidence.raw_run_ordinal]
        title_key = evidence.title_template_sha256.lower()
        previous_title_key = (
            previous_evidence.title_template_sha256.lower()
            if previous_evidence is not None
            else None
        )
        if previous_evidence is not None and title_key == previous_title_key:
            delta = evidence.attempt - previous_evidence.attempt
            if delta not in (0, 1):
                raise GscVideoRecoveryError(
                    "Fixed-header attempt sequence for one contiguous trainer title must "
                    "stay constant through party replacement or advance by exactly one."
                )
        same_attempt = (
            previous_evidence is not None
            and title_key == previous_title_key
            and evidence.attempt == previous_evidence.attempt
        )
        if same_attempt:
            groups[-1].append(raw)
        else:
            groups.append([raw])
        previous_evidence = evidence
    return tuple(tuple(group) for group in groups)


def resolve_battles_from_fixed_header_semantics(
    raw_runs: Sequence[RawStateRun],
    semantics: Sequence[FixedHeaderSemanticEvidence],
) -> tuple[ResolvedBattleRun, ...]:
    """Deterministically coalesce raw mode runs into physical attempts."""

    groups = _semantic_battle_groups(raw_runs, semantics)
    evidence_by_raw = {row.raw_run_ordinal: row for row in semantics}
    return tuple(
        ResolvedBattleRun(
            ordinal=ordinal,
            start_frame=group[0].start_frame,
            end_frame=group[-1].end_frame,
            source_raw_run_ordinals=tuple(row.ordinal for row in group),
            identity_probe_frame=evidence_by_raw[group[0].ordinal].probe_frame,
        )
        for ordinal, group in enumerate(groups, start=1)
    )


def validate_run_resolution(
    raw_runs: Sequence[RawStateRun],
    resolution: RunResolution | None,
) -> tuple[ResolvedBattleRun, ...]:
    """Require complete caller-owned handling of every raw Battle run."""

    if resolution is None:
        raise GscVideoRecoveryError(
            "Raw Battle runs require a supplied deterministic resolution receipt; "
            "this module has no implicit bounce filter."
        )
    if not resolution.policy_id.strip():
        raise GscVideoRecoveryError("Run resolution receipt lacks a deterministic policy ID.")
    digest = raw_runs_sha256(raw_runs)
    if resolution.raw_runs_sha256.lower() != digest:
        raise GscVideoRecoveryError("Run resolution receipt is stale for these raw runs.")
    if resolution.policy_id != SEMANTIC_RUN_RESOLUTION_POLICY_ID:
        raise GscVideoRecoveryError(
            "Run resolution uses an obsolete bounce policy; regenerate it with the "
            "fixed-header party-replacement merge policy."
        )
    if resolution.discarded_battle_runs:
        raise GscVideoRecoveryError(
            "The fixed-header party-replacement policy may not discard raw Battle runs."
        )
    semantic_battles = resolve_battles_from_fixed_header_semantics(
        raw_runs,
        resolution.fixed_header_semantics,
    )
    by_ordinal = {row.ordinal: row for row in raw_runs}
    raw_battle_ordinals = {row.ordinal for row in raw_runs if row.state == "battle"}
    handled: set[int] = set()
    previous_end = -1
    if len(resolution.battles) != len(semantic_battles):
        raise GscVideoRecoveryError(
            "Resolved battle count does not match the fixed title+attempt semantic groups."
        )
    for ordinal, battle in enumerate(resolution.battles, start=1):
        if battle.ordinal != ordinal:
            raise GscVideoRecoveryError("Resolved battle ordinals must be dense and ordered.")
        if battle.start_frame < previous_end or battle.end_frame <= battle.start_frame:
            raise GscVideoRecoveryError("Resolved battle ranges overlap or are empty.")
        source = tuple(battle.source_raw_run_ordinals)
        if not source or len(set(source)) != len(source):
            raise GscVideoRecoveryError("Resolved battle lacks unique source raw-run ordinals.")
        source_rows: list[RawStateRun] = []
        for raw_ordinal in source:
            row = by_ordinal.get(raw_ordinal)
            if row is None or row.state != "battle":
                raise GscVideoRecoveryError(
                    "Resolved battles may reference only existing raw Battle runs."
                )
            if raw_ordinal in handled:
                raise GscVideoRecoveryError("A raw Battle run was handled more than once.")
            handled.add(raw_ordinal)
            source_rows.append(row)
        if battle.start_frame != min(row.start_frame for row in source_rows):
            raise GscVideoRecoveryError("Resolved battle start is not source-run bound.")
        if battle.end_frame != max(row.end_frame for row in source_rows):
            raise GscVideoRecoveryError("Resolved battle end is not source-run bound.")
        expected = semantic_battles[ordinal - 1]
        if (
            source != expected.source_raw_run_ordinals
            or battle.start_frame != expected.start_frame
            or battle.end_frame != expected.end_frame
            or battle.identity_probe_frame != expected.identity_probe_frame
        ):
            raise GscVideoRecoveryError(
                "Resolved battle must merge every consecutive raw run with the same fixed "
                "title+attempt and must split changed attempts."
            )
        if not any(
            row.start_frame <= battle.identity_probe_frame < row.end_frame
            for row in source_rows
        ):
            raise GscVideoRecoveryError(
                "Resolved battle identity probe must lie inside one of its raw Battle runs."
            )
        previous_end = battle.end_frame

    discarded_seen: set[int] = set()
    for discarded in resolution.discarded_battle_runs:
        raw_ordinal = discarded.raw_run_ordinal
        if (
            raw_ordinal not in raw_battle_ordinals
            or raw_ordinal in handled
            or raw_ordinal in discarded_seen
        ):
            raise GscVideoRecoveryError("Discarded raw Battle receipt is invalid or duplicated.")
        if not discarded.reason_code.strip() or not discarded.evidence.strip():
            raise GscVideoRecoveryError(
                "Discarding a raw Battle run requires a reason code and evidence."
            )
        discarded_seen.add(raw_ordinal)
    if handled | discarded_seen != raw_battle_ordinals:
        missing = sorted(raw_battle_ordinals - handled - discarded_seen)
        raise GscVideoRecoveryError(
            f"Run resolution does not handle every raw Battle run: {missing}."
        )
    return resolution.battles


def _valid_sha256(value: str) -> bool:
    return re.fullmatch(r"[0-9a-fA-F]{64}", str(value or "")) is not None


def validate_projection_proof(
    anchors: Sequence[ProjectionAnchor],
    *,
    expected_offset_frames: int = EXPECTED_MAIN_PROJECTION_FRAMES,
    residual_tolerance_frames: int = 0,
) -> ProjectionProof:
    """Prove -6f from separated deterministic cross-media pixel correlations."""

    if residual_tolerance_frames < 0:
        raise GscVideoRecoveryError("Projection residual tolerance cannot be negative.")
    ordered = tuple(sorted(anchors, key=lambda row: row.vertical_frame))
    if len(ordered) < MIN_PROJECTION_ANCHORS:
        raise GscVideoRecoveryError(
            f"Main projection requires at least {MIN_PROJECTION_ANCHORS} pixel-correlation anchors."
        )
    if any(
        right.vertical_frame - left.vertical_frame < MIN_PROJECTION_ANCHOR_SEPARATION_FRAMES
        for left, right in zip(ordered, ordered[1:])
    ):
        raise GscVideoRecoveryError("Projection anchors are not sufficiently separated in time.")
    deltas: list[int] = []
    for row in ordered:
        if row.method != PROJECTION_METHOD:
            raise GscVideoRecoveryError("Projection anchor uses an unapproved proof method.")
        if row.vertical_frame < 0 or row.main_frame < 0:
            raise GscVideoRecoveryError("Projection anchor frame numbers must be non-negative.")
        if not _valid_sha256(row.vertical_window_sha256) or not _valid_sha256(
            row.main_window_sha256
        ):
            raise GscVideoRecoveryError("Projection anchor lacks window SHA-256 evidence.")
        if (
            not math.isfinite(row.normalized_distance)
            or not math.isfinite(row.runner_up_distance)
            or row.normalized_distance < 0
            or row.runner_up_distance < row.normalized_distance
            or row.normalized_distance > MAX_PROJECTION_MATCH_DISTANCE
            or row.runner_up_distance - row.normalized_distance
            < MIN_PROJECTION_RUNNER_UP_MARGIN
        ):
            raise GscVideoRecoveryError("Projection anchor pixel match is weak or ambiguous.")
        delta = row.main_frame - row.vertical_frame
        if abs(delta - expected_offset_frames) > residual_tolerance_frames:
            raise GscVideoRecoveryError(
                f"Projection anchor has residual/drift: {delta}f != {expected_offset_frames}f."
            )
        deltas.append(delta)
    if max(deltas) - min(deltas) > residual_tolerance_frames:
        raise GscVideoRecoveryError("Projection anchors prove temporal drift.")
    evidence_rows = [row.__dict__ for row in ordered]
    evidence_sha = hashlib.sha256(
        json.dumps(evidence_rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return ProjectionProof(
        expected_offset_frames=expected_offset_frames,
        residual_tolerance_frames=residual_tolerance_frames,
        anchors=ordered,
        evidence_sha256=evidence_sha,
    )


def _validated_extracted_windows(
    extractor: RawWindowExtractor,
    capture_path: Path,
    frames: Sequence[int],
    deadline: RecoveryDeadline,
    *,
    label: str,
) -> dict[int, bytes]:
    deadline.check(f"starting {label} projection-window extraction")
    supplied = extractor(capture_path, frames, deadline)
    if not isinstance(supplied, Mapping):
        raise GscVideoRecoveryError(f"{label} projection extractor returned no frame mapping.")
    expected = set(frames)
    actual = set(supplied)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise GscVideoRecoveryError(
            f"{label} projection extractor frame mismatch: missing={missing}, extra={extra}."
        )
    normalized: dict[int, bytes] = {}
    for frame in frames:
        sample = supplied[frame]
        if not isinstance(sample, (bytes, bytearray, memoryview)) or not sample:
            raise GscVideoRecoveryError(
                f"{label} projection extractor returned an empty/non-byte frame at {frame}."
            )
        normalized[frame] = bytes(sample)
    lengths = {len(sample) for sample in normalized.values()}
    if len(lengths) != 1:
        raise GscVideoRecoveryError(
            f"{label} projection extractor returned inconsistent window dimensions."
        )
    deadline.check(f"finishing {label} projection-window extraction")
    return normalized


def _discover_projection_anchor_rows(
    vertical_capture_path: Path,
    main_capture_path: Path,
    *,
    vertical_frames: Sequence[int],
    deadline: RecoveryDeadline,
    search_radius_frames: int,
    expected_offset_frames: int,
    vertical_geometry: GrayWindowGeometry | None,
    main_geometry: GrayWindowGeometry | None,
    raw_window_extractor: RawWindowExtractor | None,
    ffmpeg: str,
) -> tuple[ProjectionAnchor, ...]:
    ordered_vertical = _normalized_probe_frames(vertical_frames)
    if len(ordered_vertical) < MIN_PROJECTION_ANCHORS:
        raise GscVideoRecoveryError(
            f"Main projection requires at least {MIN_PROJECTION_ANCHORS} discovery anchors."
        )
    if any(
        right - left < MIN_PROJECTION_ANCHOR_SEPARATION_FRAMES
        for left, right in zip(ordered_vertical, ordered_vertical[1:])
    ):
        raise GscVideoRecoveryError("Projection discovery anchors are not sufficiently separated.")
    if expected_offset_frames != EXPECTED_MAIN_PROJECTION_FRAMES:
        raise GscVideoRecoveryError(
            f"Video recovery can only prove the fixed {EXPECTED_MAIN_PROJECTION_FRAMES}f projection."
        )
    if (
        isinstance(search_radius_frames, bool)
        or not isinstance(search_radius_frames, int)
        or not 1 <= search_radius_frames <= MAX_PROJECTION_SEARCH_RADIUS_FRAMES
    ):
        raise GscVideoRecoveryError(
            "Projection candidate radius must be an integer in "
            f"[1, {MAX_PROJECTION_SEARCH_RADIUS_FRAMES}]."
        )
    if ordered_vertical[0] + expected_offset_frames - search_radius_frames < 0:
        raise GscVideoRecoveryError("Projection candidate window crosses before main frame zero.")

    if raw_window_extractor is not None:
        if vertical_geometry is not None or main_geometry is not None:
            raise GscVideoRecoveryError(
                "Choose caller-supplied projection extraction or fixed geometries, not both."
            )
        vertical_extractor = raw_window_extractor
        main_extractor = raw_window_extractor
    else:
        if vertical_geometry is None or main_geometry is None:
            raise GscVideoRecoveryError(
                "Projection discovery requires both fixed geometries or a raw window extractor."
            )
        if (
            vertical_geometry.sample_width != main_geometry.sample_width
            or vertical_geometry.sample_height != main_geometry.sample_height
        ):
            raise GscVideoRecoveryError(
                "Projection geometries must normalize to identical sample dimensions."
            )

        def vertical_extractor(
            path: Path,
            frames: Sequence[int],
            shared_deadline: RecoveryDeadline,
        ) -> Mapping[int, bytes]:
            return extract_fixed_gray_probe_frames(
                path,
                probe_frames=frames,
                geometry=vertical_geometry,
                deadline=shared_deadline,
                ffmpeg=ffmpeg,
            )

        def main_extractor(
            path: Path,
            frames: Sequence[int],
            shared_deadline: RecoveryDeadline,
        ) -> Mapping[int, bytes]:
            return extract_fixed_gray_probe_frames(
                path,
                probe_frames=frames,
                geometry=main_geometry,
                deadline=shared_deadline,
                ffmpeg=ffmpeg,
            )

    candidate_by_vertical = {
        frame: tuple(
            range(
                frame + expected_offset_frames - search_radius_frames,
                frame + expected_offset_frames + search_radius_frames + 1,
            )
        )
        for frame in ordered_vertical
    }
    main_frames = tuple(
        sorted({candidate for rows in candidate_by_vertical.values() for candidate in rows})
    )
    vertical_samples = _validated_extracted_windows(
        vertical_extractor,
        vertical_capture_path.resolve(),
        ordered_vertical,
        deadline,
        label="vertical",
    )
    main_samples = _validated_extracted_windows(
        main_extractor,
        main_capture_path.resolve(),
        main_frames,
        deadline,
        label="main",
    )
    sample_lengths = {
        *(len(sample) for sample in vertical_samples.values()),
        *(len(sample) for sample in main_samples.values()),
    }
    if len(sample_lengths) != 1:
        raise GscVideoRecoveryError(
            "Vertical and main projection extractors returned different window dimensions."
        )

    anchors: list[ProjectionAnchor] = []
    for vertical_frame in ordered_vertical:
        deadline.check(f"matching projection anchor at vertical frame {vertical_frame}")
        vertical_sample = vertical_samples[vertical_frame]
        scores = sorted(
            (
                _normalized_sad(vertical_sample, main_samples[main_frame]),
                main_frame,
            )
            for main_frame in candidate_by_vertical[vertical_frame]
        )
        if len(scores) < 2:
            raise GscVideoRecoveryError(
                "Projection discovery requires a best and runner-up candidate."
            )
        (best_distance, main_frame), (runner_up_distance, _runner_up_frame) = scores[:2]
        anchors.append(
            ProjectionAnchor(
                vertical_frame=vertical_frame,
                main_frame=main_frame,
                normalized_distance=best_distance,
                runner_up_distance=runner_up_distance,
                vertical_window_sha256=hashlib.sha256(vertical_sample).hexdigest(),
                main_window_sha256=hashlib.sha256(main_samples[main_frame]).hexdigest(),
            )
        )
    return tuple(anchors)


def discover_projection_anchors(
    vertical_capture_path: Path,
    main_capture_path: Path,
    *,
    vertical_frames: Sequence[int],
    deadline: RecoveryDeadline,
    search_radius_frames: int = 2,
    expected_offset_frames: int = EXPECTED_MAIN_PROJECTION_FRAMES,
    vertical_geometry: GrayWindowGeometry | None = None,
    main_geometry: GrayWindowGeometry | None = None,
    raw_window_extractor: RawWindowExtractor | None = None,
    ffmpeg: str = "ffmpeg",
) -> tuple[ProjectionAnchor, ...]:
    """Discover unique bounded matches and return only fully validated anchor rows.

    A supplied extractor is called as ``extractor(path, frames, deadline)`` and
    must return one equally sized raw byte window per requested exact 60fps
    frame.  Otherwise both fixed geometries are decoded with ffmpeg.
    """

    anchors = _discover_projection_anchor_rows(
        vertical_capture_path,
        main_capture_path,
        vertical_frames=vertical_frames,
        deadline=deadline,
        search_radius_frames=search_radius_frames,
        expected_offset_frames=expected_offset_frames,
        vertical_geometry=vertical_geometry,
        main_geometry=main_geometry,
        raw_window_extractor=raw_window_extractor,
        ffmpeg=ffmpeg,
    )
    return validate_projection_proof(
        anchors,
        expected_offset_frames=EXPECTED_MAIN_PROJECTION_FRAMES,
        residual_tolerance_frames=0,
    ).anchors


def discover_projection_proof(
    vertical_capture_path: Path,
    main_capture_path: Path,
    *,
    vertical_frames: Sequence[int],
    deadline: RecoveryDeadline,
    search_radius_frames: int = 2,
    expected_offset_frames: int = EXPECTED_MAIN_PROJECTION_FRAMES,
    vertical_geometry: GrayWindowGeometry | None = None,
    main_geometry: GrayWindowGeometry | None = None,
    raw_window_extractor: RawWindowExtractor | None = None,
    ffmpeg: str = "ffmpeg",
) -> ProjectionProof:
    """Discover and prove the exact drift-free -6f vertical-to-main mapping."""

    anchors = _discover_projection_anchor_rows(
        vertical_capture_path,
        main_capture_path,
        vertical_frames=vertical_frames,
        deadline=deadline,
        search_radius_frames=search_radius_frames,
        expected_offset_frames=expected_offset_frames,
        vertical_geometry=vertical_geometry,
        main_geometry=main_geometry,
        raw_window_extractor=raw_window_extractor,
        ffmpeg=ffmpeg,
    )
    return validate_projection_proof(
        anchors,
        expected_offset_frames=EXPECTED_MAIN_PROJECTION_FRAMES,
        residual_tolerance_frames=0,
    )


def project_vertical_frame_to_main(frame: int, proof: ProjectionProof) -> int:
    if isinstance(frame, bool) or frame < 0:
        raise GscVideoRecoveryError("Vertical frame projection requires a non-negative integer.")
    # Revalidate the immutable proof payload so hand-constructed or stale proof
    # objects cannot turn the documented -6f value into a blind assumption.
    current = validate_projection_proof(
        proof.anchors,
        expected_offset_frames=proof.expected_offset_frames,
        residual_tolerance_frames=proof.residual_tolerance_frames,
    )
    if current.evidence_sha256 != proof.evidence_sha256:
        raise GscVideoRecoveryError("Projection proof evidence hash is stale.")
    projected = frame + proof.expected_offset_frames
    if projected < 0:
        raise GscVideoRecoveryError("Projected main-recording frame is negative.")
    return projected


_IDENTITY_METADATA: dict[str, tuple[str, str, str, int | None]] = {
    **{
        f"LEADER {name}": (name.title(), "leader", re.sub(r"[^A-Z0-9]+", "_", name), 1)
        for name in (
            "FALKNER", "BUGSY", "WHITNEY", "MORTY", "CHUCK", "JASMINE",
            "PRYCE", "CLAIR", "BROCK", "MISTY", "LT. SURGE", "ERIKA",
            "JANINE", "SABRINA", "BLAINE", "BLUE",
        )
    },
    **{
        f"ELITE FOUR {name}": (name.title(), "leader", name, 1)
        for name in ("WILL", "KOGA", "BRUNO", "KAREN")
    },
    "CHAMPION LANCE": ("Lance", "leader", "LANCE", 1),
    "LEGEND RED": ("Red", "leader", "RED", 1),
    "RIVAL1": ("Rival", "rival", "RIVAL1", None),
    "RIVAL2": ("Rival", "rival", "RIVAL2", None),
}


def finite_komikax_identity_titles() -> tuple[str, ...]:
    return tuple(sorted(_IDENTITY_METADATA))


def _load_komikax_atlas() -> dict[str, dict[str, Any]]:
    if not _KOMIKAX_ATLAS_B85:
        raise GscVideoRecoveryError("Bundled KOMIKAX finite template atlas is missing.")
    try:
        value = json.loads(
            zlib.decompress(base64.b85decode(_KOMIKAX_ATLAS_B85.encode("ascii"))).decode(
                "utf-8"
            )
        )
    except (ValueError, zlib.error, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise GscVideoRecoveryError("Bundled KOMIKAX template atlas is corrupt.") from exc
    if not isinstance(value, dict) or set(value) != set(_IDENTITY_METADATA):
        raise GscVideoRecoveryError("Bundled KOMIKAX atlas has an unexpected finite title set.")
    return value


def _otsu_threshold(gray: bytes) -> int:
    if not gray:
        raise GscVideoRecoveryError("Header identity sample is empty.")
    histogram = [0] * 256
    for value in gray:
        histogram[value] += 1
    total = len(gray)
    total_sum = sum(index * count for index, count in enumerate(histogram))
    background_weight = 0
    background_sum = 0
    best_variance = -1.0
    best_threshold = 0
    for threshold, count in enumerate(histogram):
        background_weight += count
        if background_weight == 0:
            continue
        foreground_weight = total - background_weight
        if foreground_weight == 0:
            break
        background_sum += threshold * count
        background_mean = background_sum / background_weight
        foreground_mean = (total_sum - background_sum) / foreground_weight
        variance = background_weight * foreground_weight * (
            background_mean - foreground_mean
        ) ** 2
        if variance > best_variance:
            best_variance = variance
            best_threshold = threshold
    return best_threshold


def _tight_dark_bitmap(gray: bytes, width: int, height: int) -> tuple[int, int, bytes]:
    if len(gray) != width * height or width <= 0 or height <= 0:
        raise GscVideoRecoveryError("Header identity sample dimensions are invalid.")
    threshold = _otsu_threshold(gray)
    # KOMIKAX title ink is the dark Otsu class on the cyan module background.
    points = [index for index, value in enumerate(gray) if value <= threshold]
    if not points or len(points) >= len(gray) * 0.6:
        raise GscVideoRecoveryError("Header identity sample has no isolated dark title ink.")
    xs = [index % width for index in points]
    ys = [index // width for index in points]
    left, right = min(xs), max(xs) + 1
    top, bottom = min(ys), max(ys) + 1
    tight_width = right - left
    tight_height = bottom - top
    mask = bytearray(tight_width * tight_height)
    for y in range(top, bottom):
        for x in range(left, right):
            if gray[y * width + x] <= threshold:
                mask[(y - top) * tight_width + (x - left)] = 1
    return tight_width, tight_height, bytes(mask)


def _unpack_template(row: Mapping[str, Any]) -> tuple[int, int, bytes]:
    width = int(row.get("w") or 0)
    height = int(row.get("h") or 0)
    packed = base64.b85decode(str(row.get("bits") or "").encode("ascii"))
    stride = (width + 7) // 8
    if width <= 0 or height <= 0 or len(packed) != stride * height:
        raise GscVideoRecoveryError("Bundled KOMIKAX bitmap dimensions are corrupt.")
    mask = bytearray(width * height)
    for y in range(height):
        for x in range(width):
            mask[y * width + x] = (packed[y * stride + x // 8] >> (7 - x % 8)) & 1
    return width, height, bytes(mask)


def _resample_binary(
    mask: bytes,
    source_width: int,
    source_height: int,
    target_width: int,
    target_height: int,
) -> bytes:
    output = bytearray(target_width * target_height)
    for y in range(target_height):
        source_y = min(source_height - 1, (y * source_height) // target_height)
        for x in range(target_width):
            source_x = min(source_width - 1, (x * source_width) // target_width)
            output[y * target_width + x] = mask[source_y * source_width + source_x]
    return bytes(output)


def _tight_binary_bitmap(mask: bytes, width: int, height: int) -> tuple[int, int, bytes]:
    points = [index for index, value in enumerate(mask) if value]
    if not points:
        raise GscVideoRecoveryError("Bundled KOMIKAX template contains no ink.")
    xs = [index % width for index in points]
    ys = [index // width for index in points]
    left, right = min(xs), max(xs) + 1
    top, bottom = min(ys), max(ys) + 1
    tight_width = right - left
    tight_height = bottom - top
    tight = bytearray(tight_width * tight_height)
    for y in range(top, bottom):
        source = y * width + left
        target = (y - top) * tight_width
        tight[target:target + tight_width] = mask[source:source + tight_width]
    return tight_width, tight_height, bytes(tight)


def _binary_union_distance(left: bytes, right: bytes) -> float:
    if len(left) != len(right) or not left:
        raise GscVideoRecoveryError("KOMIKAX masks have inconsistent dimensions.")
    union = sum(1 for a, b in zip(left, right) if a or b)
    if union == 0:
        return 1.0
    return sum(1 for a, b in zip(left, right) if a != b) / union


def _dilate_binary(mask: bytes, width: int, height: int) -> bytes:
    """Return the closed one-pixel neighbourhood of a finite title mask."""

    if len(mask) != width * height or width <= 0 or height <= 0:
        raise GscVideoRecoveryError("KOMIKAX mask dimensions are invalid.")
    output = bytearray(width * height)
    for index, value in enumerate(mask):
        if not value:
            continue
        x = index % width
        y = index // width
        for target_y in range(max(0, y - 1), min(height, y + 2)):
            row = target_y * width
            for target_x in range(max(0, x - 1), min(width, x + 2)):
                output[row + target_x] = 1
    return bytes(output)


def _tolerant_binary_distance(left: bytes, right: bytes, width: int, height: int) -> float:
    """Measure symmetric ink misses with one-pixel rasterizer tolerance.

    Chromium/Skia and the offline FreeType atlas can choose adjacent boundary
    pixels for the same immutable KOMIKAX glyph.  This remains a closed bitmap
    comparison: a pixel is forgiven only when the other finite mask has ink in
    its immediate 3x3 neighbourhood.  It does not segment or recognize text.
    """

    if len(left) != len(right) or len(left) != width * height:
        raise GscVideoRecoveryError("KOMIKAX masks have inconsistent dimensions.")
    left_ink = sum(left)
    right_ink = sum(right)
    if not left_ink or not right_ink:
        return 1.0
    left_neighbourhood = _dilate_binary(left, width, height)
    right_neighbourhood = _dilate_binary(right, width, height)
    left_misses = sum(
        1 for ink, nearby in zip(left, right_neighbourhood) if ink and not nearby
    )
    right_misses = sum(
        1 for ink, nearby in zip(right, left_neighbourhood) if ink and not nearby
    )
    return (left_misses + right_misses) / (left_ink + right_ink)


def match_finite_komikax_identity(
    gray_header_title: bytes,
    *,
    width: int = HEADER_TITLE_WIDTH,
    height: int = HEADER_TITLE_HEIGHT,
    maximum_distance: float = 0.08,
    minimum_runner_up_margin: float = 0.012,
) -> IdentityMatch:
    """Match one header title against the closed KOMIKAX leader/rival atlas."""

    observed_width, observed_height, observed = _tight_dark_bitmap(
        gray_header_title, width, height
    )
    scores: list[tuple[float, str]] = []
    for title, row in _load_komikax_atlas().items():
        template_width, template_height, template = _unpack_template(row)
        template_width, template_height, template = _tight_binary_bitmap(
            template, template_width, template_height
        )
        resized = _resample_binary(
            observed,
            observed_width,
            observed_height,
            template_width,
            template_height,
        )
        scores.append(
            (
                _tolerant_binary_distance(
                    resized,
                    template,
                    template_width,
                    template_height,
                ),
                title,
            )
        )
    scores.sort(key=lambda value: (value[0], value[1]))
    best_distance, title = scores[0]
    runner_up_distance = scores[1][0]
    if (
        best_distance > maximum_distance
        or runner_up_distance - best_distance < minimum_runner_up_margin
    ):
        raise GscVideoRecoveryError(
            "Header title does not uniquely match the finite KOMIKAX leader/rival atlas."
        )
    identity, role, trainer_class, trainer_id = _IDENTITY_METADATA[title]
    evidence_sha = hashlib.sha256(
        gray_header_title
        + title.encode("ascii")
        + f"{best_distance:.12f}:{runner_up_distance:.12f}".encode("ascii")
    ).hexdigest()
    return IdentityMatch(
        display_text=title,
        identity=identity,
        role=role,
        trainer_class=trainer_class,
        trainer_id=trainer_id,
        normalized_distance=best_distance,
        runner_up_distance=runner_up_distance,
        evidence_sha256=evidence_sha,
    )


def build_mapped_recovered_attempts(
    *,
    resolution: RunResolution,
    raw_runs: Sequence[RawStateRun],
    projection_proof: ProjectionProof,
    identity_matches: Mapping[int, IdentityMatch | None],
    rival_trainer_ids: Mapping[int, int] | None = None,
) -> dict[str, Any]:
    """Build the runner integration seam without manufacturing session events."""

    battles = validate_run_resolution(raw_runs, resolution)
    rival_trainer_ids = rival_trainer_ids or {}
    rows: list[dict[str, Any]] = []
    identity_counts: dict[str, int] = {}
    for battle in battles:
        match = identity_matches.get(battle.ordinal)
        if match is None:
            role = "trainer"
            identity = "Unclassified physical battle"
            trainer_class: str | None = None
            trainer_id: int | None = None
            checkpoint_key: str | None = None
            battle_key = f"VIDEO_PHYSICAL:{battle.ordinal}"
            identity_authority = "finite_intro_identity_atlas_no_match_non_intro_battle"
        else:
            role = match.role
            identity = match.identity
            trainer_class = match.trainer_class
            trainer_id = match.trainer_id
            if role == "rival":
                supplied_id = rival_trainer_ids.get(battle.ordinal)
                if isinstance(supplied_id, bool) or not isinstance(supplied_id, int) or supplied_id <= 0:
                    raise GscVideoRecoveryError(
                        "RIVAL1/RIVAL2 header identity does not encode trainerId; an exact "
                        "deterministic rival trainerId receipt is required."
                    )
                trainer_id = supplied_id
            checkpoint_key = identity if role == "leader" else None
            battle_key = f"{trainer_class}:{trainer_id}"
            identity_authority = "bundled_finite_KOMIKAX_header_template_match"
        source_start = project_vertical_frame_to_main(battle.start_frame, projection_proof)
        source_end = project_vertical_frame_to_main(battle.end_frame, projection_proof)
        identity_key = battle_key.casefold()
        identity_ordinal = identity_counts.get(identity_key, 0) + 1
        identity_counts[identity_key] = identity_ordinal
        rows.append(
            {
                "attempt_ordinal": battle.ordinal,
                "attempt_id": f"{battle_key}:attempt-{identity_ordinal}",
                "battle_key": battle_key,
                "canonical_identity": battle_key,
                "identity_attempt_ordinal": identity_ordinal,
                "identity": identity,
                "role": role,
                "trainer_class": trainer_class,
                "trainer_id": trainer_id,
                "checkpoint_key": checkpoint_key,
                "vertical_physical_start_frame": battle.start_frame,
                "vertical_physical_end_frame": battle.end_frame,
                "vertical_identity_probe_frame": battle.identity_probe_frame,
                "session_start_frame": battle.start_frame,
                "session_end_frame": battle.end_frame,
                "source_start_frame": source_start,
                "source_physical_start_frame": source_start,
                "source_end_frame": source_end,
                "source_duration_frames": source_end - source_start,
                "source_frame": source_start,
                "outcome": "Unknown",
                "direct_end_event_index": None,
                "start_authority": "finalized_vertical_fixed_mode_chip_raw_run_resolution",
                "end_authority": "finalized_vertical_fixed_mode_chip_raw_run_resolution",
                "source_start_authority": (
                    "fixed_minus_6f_vertical_to_main_projection_with_"
                    f"max_{projection_proof.residual_tolerance_frames}f_audited_residual"
                ),
                "source_end_authority": (
                    "fixed_minus_6f_vertical_to_main_projection_with_"
                    f"max_{projection_proof.residual_tolerance_frames}f_audited_residual"
                ),
                "outcome_authority": "not_recovered_from_pixels",
                "identity_authority": identity_authority,
                "identity_match": match.__dict__ if match is not None else None,
                "run_resolution_policy_id": resolution.policy_id,
                "raw_runs_sha256": resolution.raw_runs_sha256,
                "projection_offset_frames": projection_proof.expected_offset_frames,
                "projection_offset_seconds": (
                    projection_proof.expected_offset_frames / FPS
                ),
                "projection_proof_sha256": projection_proof.evidence_sha256,
                "source_mapping_required": False,
                "final_timeline_mapping_required": True,
                "already_mapped_to_main_source": True,
                "synthetic_session_events": False,
            }
        )
    payload = {
        "schema": MAPPED_ATTEMPTS_SCHEMA,
        "status": "pass",
        "recovery_schema": RECOVERY_SCHEMA,
        "fps": FPS,
        "attempts": rows,
        "attempt_count": len(rows),
        "run_resolution": {
            "policy_id": resolution.policy_id,
            "raw_runs_sha256": resolution.raw_runs_sha256,
            "fixed_header_semantics_sha256": fixed_header_semantics_sha256(
                resolution.fixed_header_semantics
            ),
            "fixed_header_semantic_count": len(resolution.fixed_header_semantics),
            "discarded_battle_runs": [row.__dict__ for row in resolution.discarded_battle_runs],
        },
        "projection": {
            "offset_frames": projection_proof.expected_offset_frames,
            "offset_seconds": projection_proof.expected_offset_frames / FPS,
            "proof_sha256": projection_proof.evidence_sha256,
            "anchor_count": len(projection_proof.anchors),
        },
        "no_ocr": True,
        "no_model": True,
        "no_llm": True,
        "synthetic_session_events": False,
    }
    payload["attempts_sha256"] = hashlib.sha256(
        json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return payload
