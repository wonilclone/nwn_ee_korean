# 대화 파일 번역 점검 가이드

## 점검 범위
- PC_ 파일 460개 + 매칭 NPC 파일
- 총 점검 대사: PC 30,256 + NPC 26,119 + 동료 Henchman 약 7,000 = **약 63,000 대사**

## 점검 방법론

### 1. 파일 페어링 원칙
- PC_xxx.csv의 NPC 대응 파일을 DLG 칼럼으로 매칭
- 동료 파일은 Henchman_*.csv가 NPC 대응
- small 파일(PC_M_small 등)은 NPC_*_small.csv 등 다수 파일 대응

### 2. 점검 항목
1. **직역투 다듬기**: 영어 어순/표현을 그대로 옮긴 부분
2. **오역 확인**: TextEng vs Text 대조
3. **말투 일관성**:
   - NPC: 캐릭터별 존댓말/반말 일관
   - PC: 지능 낮음(반말·단순)/보통 이상(일반) 두 케이스
4. **대화 연결성**: PC↔NPC 대사가 맥락상 자연스럽게 이어지는지

### 3. PC 지능 구분 패턴
- 지능 낮은 PC 대사 특징: 짧고 단순한 문장, 반말, 어눌한 표현
- DLG 조건 스크립트로 분기됨 (같은 DLG 내 다른 StrRef)
- 지능 정상 PC는 상황에 따라 존댓말/반말 혼용 가능 (NPC 관계에 따라)

### 4. 작업 흐름
```
1. PC_ 파일 열기
2. basename으로 NPC 파일 찾기 (grep DLG명 또는 아래 매핑 참조)
3. PC+NPC 대사를 함께 읽으며 점검
4. 수정사항 적용
5. 체크리스트 완료 표시
```

## 그룹별 체크리스트

### OC-프롤로그/챕터1 (59파일, 5,156 대사)
- [x] PC_m0q01a01pave (75) → PAVE
- [x] PC_m0q01a02olge (99) → OLGE
- [x] PC_m0q01a03bern (60) → BERN
- [x] PC_m0q01a05erda (41) → NPC_E_small
- [x] PC_m0q01a05gilb (89) → Gilbert
- [x] PC_m0q01a05herb (112) → HERB
- [x] PC_m0q01a06chan (91) → Chandra
- [x] PC_m0q01a06jaro (84) → JARO
- [x] PC_m0q01a06zedi (46) → Zedir
- [x] PC_m0q01a07anse (46) → Ansel
- [x] PC_m0q01a07elyn (88) → ELYN
- [x] PC_m0q01a07tabi (44) → TABI
- [x] PC_m0q01a08kett (95) → KETT
- [x] PC_m0q01a08shad (95) → Shade
- [x] PC_m0q01a08silk (91) → Silk
- [x] PC_m0q01a09arib (54) → ARIB
- [x] PC_m0q01a0bim (118) → BIM
- [x] PC_m0q01a12pave (98) → PAVE
- [x] PC_m0q01a15gend (43) → GEND
- [x] PC_m0q01a23fent (78) → FENT
- [x] PC_m1q00deathcleric (75) → DEATHCLERIC
- [x] PC_m1q01a03eltr (49) → ELTR
- [x] PC_m1q02allhelm (64) → ALLHELM
- [x] PC_m1q02alltowf (43) → NPC_A_small
- [x] PC_m1q02alltown (42) → NPC_A_small
- [x] PC_m1q1_gateblak (86) → GATEBLAK
- [x] PC_m1q1_gatedock (87) → GATEDOCK
- [x] PC_m1q1_gatepen (86) → GATEPEN
- [x] PC_m1q1a00com1 (103) → Commoner
- [x] PC_m1q1a00com2 (101) → Commoner
- [x] PC_m1q1a00com3 (60) → Commoner
- [x] PC_m1q1a00gen1 (101) → GEN1
- [x] PC_m1q1a00gen2 (101) → GEN2
- [x] PC_m1q1a00gen3 (91) → GEN3
- [x] PC_m1q1a00gen4 (110) → GEN4
- [x] PC_m1q1a00gen5 (114) → GEN5
- [x] PC_m1q1a00guard01 (87) → GUARD01
- [x] PC_m1q1a00harlot (93) → HARLOT
- [x] PC_m1q1a01olef (177) → OLEF
- [x] PC_m1q1a01push (86) → PUSH
- [x] PC_m1q1a01s1br (73) → BR
- [x] PC_m1q1a01s1wm (65) → WM
- [x] PC_m1q1a05nyat (128) → NYAT
- [x] PC_m1q1a05s1m1 (36) → batch01, batch05
- [x] PC_m1q1a06gill (136) → GILL
- [x] PC_m1q1a06luce (103) → LUCE
- [x] PC_m1q1a06malp (70) → MALP
- [x] PC_m1q1a06ophal (128) → OPHAL
- [x] PC_m1q1a06tamo (167) → TAMO
- [x] PC_m1q1a06tani (112) → TANI
- [x] PC_m1q1a07s1_h (53) → H
- [x] PC_m1q1a07s1bt (43) → BT
- [x] PC_m1q1a07s1g1f (41) → F
- [x] PC_m1q1a07s1g1m (41) → M
- [x] PC_m1q1a08marr (133) → MARR
- [x] PC_m1q1faribeth (231) → Aribeth
- [x] PC_m1q1fdeath (81) → FDEATH
- [x] PC_m1q1kfenthick (142) → Fenthick
- [x] PC_m1q1knurse (70) → Nurse

### OC-챕터1 지구별 (49파일, 3,855 대사)
- [x] PC_m1q2_emernik (65) → Emernik
- [x] PC_m1q2_formguard8 (56) → FORMGUARD8
- [x] PC_m1q2_kurdan (46) → Kurdan_Fenkt
- [x] PC_m1q2_sedos (118) → Sedos_Sebile
- [x] PC_m1q3ablapatr (99) → Blacklake_Patrol
- [x] PC_m1q3aclean (127) → Blacklake_cleaning_lady
- [x] PC_m1q3adryad (58) → Blacklake_Dryad
- [x] PC_m1q3adumbgua (58) → Grommin
- [x] PC_m1q3aformosa (139) → (없음)
- [x] PC_m1q3ameldanen (127) → Meldanen
- [x] PC_m1q3anobman (112) → Disgruntled_Nobleman
- [x] PC_m1q3anobwom (112) → Disgruntled_Woman
- [x] PC_m1q3asamuel (72) → ASAMUEL
- [x] PC_m1q3athurin (146) → ATHURIN
- [x] PC_m1q3gategua (88) → GATEGUA
- [x] PC_m1q3gateguard (116) → GATEGUARD
- [x] PC_m1q3i_cend2 (62) → CEND2
- [x] PC_m1q4a00com1 (97) → COM1_
- [x] PC_m1q4a00com2 (108) → COM2_
- [x] PC_m1q4a01bloodsail (31) → NPC_B_small
- [x] PC_m1q4a01burn (40) → BURN
- [x] PC_m1q4a01noble1 (99) → NOBLE1
- [x] PC_m1q4a02mugg01 (57) → MUGG01
- [x] PC_m1q4b01auct (61) → AUCT
- [x] PC_m1q4b01avista (39) → NPC_A_small
- [x] PC_m1q4b07daranei (91) → DARANEI
- [x] PC_m1q4b07gilda (64) → GILDA
- [x] PC_m1q4b08jerol (37) → NPC_J_small
- [x] PC_m1q4d03christ (68) → CHRIST
- [x] PC_m1q4d03jalek (96) → JALEK
- [x] PC_m1q4d05chef (61) → CHEF
- [x] PC_m1q4d05info (92) → INFO
- [x] PC_m1q4d05sauna (58) → SAUNA
- [x] PC_m1q4f23vengaul (41) → NPC_V_small
- [x] PC_m1q5a01atte (72) → ATTE
- [x] PC_m1q5a01gen1 (79) → GEN1
- [x] PC_m1q5a01gen2 (76) → GEN2
- [x] PC_m1q5a03ergs (59) → ERGS
- [x] PC_m1q5a07aldo (62) → Aldo
- [x] PC_m1q5a07hect (44) → NPC_H_small
- [x] PC_m1q5a09bert (151) → BERT
- [x] PC_m1q5a09hlmt (47) → HLMT
- [x] PC_m1q5a12siri (50) → SIRI
- [x] PC_m1q5a13kres (45) → KRES
- [x] PC_m1q5a14jema (82) → JEMA
- [x] PC_m1q5b01harb (135) → HARB
- [x] PC_m1q5b02drak (66) → DRAK
- [x] PC_m1q5c02walt (85) → WALT
- [x] PC_m1q5e08jard (61) → JARD

### OC-챕터1 최종 (10파일, 693 대사)
- [x] PC_m1q6_farmer (52) → FARMER
- [x] PC_m1q6a01aribeth (111) → Aribeth
- [x] PC_m1q6a01desth (47) → DESTH
- [x] PC_m1q6a01fenth (86) → FENTH
- [x] PC_m1q6a01nash (83) → NASH
- [x] PC_m1q6b01surr (69) → SURR
- [x] PC_m1q6b09fenthick (61) → FENTHICK_1
- [x] PC_m1q6f08demon (80) → DEMON
- [x] PC_m1q6f08guardian (45) → Guardian_of_Helm
- [x] PC_m1q6f11desther (59) → DESTHER_1

### OC-챕터1 기타 (1파일, 70 대사)
- [x] PC_m1qknurse (70) → QKNURSE

### OC-챕터2 (79파일, 7,436 대사)
- [x] PC_m2q1000jahel (130) → JAHEL
- [x] PC_m2q1000slmon (102) → SLMON
- [x] PC_m2q1000taran (127) → TARAN
- [x] PC_m2q1a00bmaid (48) → BMAID
- [x] PC_m2q1a00dghtr (68) → DGHTR
- [x] PC_m2q1a00farmr (76) → FARMR
- [x] PC_m2q1a00merc (56) → MERC
- [x] PC_m2q1a00mung (75) → MUNG
- [x] PC_m2q1a00prchv (79) → PRCHV
- [x] PC_m2q1a00son (101) → SON
- [x] PC_m2q1a02bran (58) → BRAN
- [x] PC_m2q1a02geth (45) → GETH
- [x] PC_m2q1a02krath (48) → KRATH
- [x] PC_m2q1a02neurk (208) → NEURK
- [x] PC_m2q1a03alhlr (82) → ALHLR
- [x] PC_m2q1a03ander (184) → ANDER
- [x] PC_m2q1a03darkt (76) → DARKT
- [x] PC_m2q1a03setra (42) → SETRA
- [x] PC_m2q1a08dellh (91) → DELLH
- [x] PC_m2q1a08kend (230) → KEND
- [x] PC_m2q1a08strge (219) → STRGE
- [x] PC_m2q1a08wyvrn (73) → WYVRN
- [x] PC_m2q1a08zor (63) → ZOR
- [x] PC_m2q1a09eltra (141) → ELTRA
- [x] PC_m2q1a10urth (54) → URTH
- [x] PC_m2q1a14odeel (67) → ODEEL
- [x] PC_m2q1aballard (49) → NPC_A_small
- [x] PC_m2q1adeath (75) → ADEATH
- [x] PC_m2q1aelaith (202) → AELAITH
- [x] PC_m2q1afarmer (56) → AFARMER
- [x] PC_m2q1afarmwife (52) → AFARMWIFE
- [x] PC_m2q1athfsto (33) → ATHFSTO
- [x] PC_m2q1binn (135) → BINN
- [x] PC_m2q1shaldr (156) → SHALDR
- [x] PC_m2q1yesgar (46) → NPC_Y_small
- [x] PC_m2q2aarche (69) → AARCHE
- [x] PC_m2q2ajanis (106) → Janis
- [x] PC_m2q2ajax2 (159) → AJAX2
- [x] PC_m2q2alent (117) → Lenton
- [x] PC_m2q2aliz (79) → ALIZ
- [x] PC_m2q2arevat (159) → AREVAT
- [x] PC_m2q2bpris (47) → NPC_D_small
- [x] PC_m2q2eaawill (170) → EAAWILL
- [x] PC_m2q2eelgar (47) → Elgar
- [x] PC_m2q2ehenna (82) → Henna
- [x] PC_m2q2ejaer (108) → Jaer
- [x] PC_m2q2ejanken (50) → Janken
- [x] PC_m2q2ewelcar (77) → Welcar
- [x] PC_m2q2fdryad (60) → Dryad
- [x] PC_m2q2fnymph2 (148) → FNYMPH2
- [x] PC_m2q2grelmar (76) → Relmar
- [x] PC_m2q2gspirit (56) → Spirit_of_the_Wood
- [x] PC_m2q2hslave1 (37) → NPC_H_small
- [x] PC_m2q2hterari (100) → Terari
- [x] PC_m2q2iorlane (98) → Orlane
- [x] PC_m2q2jbree (94) → Bree
- [x] PC_m2q2jsetara (122) → Setara
- [x] PC_m2q3_belial (53) → MBELIAL
- [x] PC_m2q3alerk (37) → NPC_A_small
- [x] PC_m2q3b01hero (47) → HERO
- [x] PC_m2q3dwanev (119) → DWANEV
- [x] PC_m2q3e_constance (185) → Constance_ODeel
- [x] PC_m2q3e_erik (157) → Erik
- [x] PC_m2q3e_ingo (101) → Ingo
- [x] PC_m2q3e_mary (84) → Mary_ODeel
- [x] PC_m2q3e_pete (122) → Pete_ODeel
- [x] PC_m2q3e_silverback (46) → NPC_S_small
- [x] PC_m2q3econstance (218) → ECONSTANCE
- [x] PC_m2q3g02cult1 (43) → CULT1
- [x] PC_m2q3g02fence (33) → NPC_F_small
- [x] PC_m2q3g02house (66) → HOUSE
- [x] PC_m2q3g02man (67) → MAN
- [x] PC_m2q3g02mayor (67) → MAYOR
- [x] PC_m2q3g02woman (72) → WOMAN
- [x] PC_m2q3h14quint2 (133) → QUINT2
- [x] PC_m2q3h_guardian (159) → GUARDIAN
- [x] PC_m2q3i_karlat (85) → Karlat_Jhareg
- [x] PC_m2q3j_quint (83) → Quint_Jhareg
- [x] PC_m2q3k10balor (51) → BALOR

### OC-챕터2 후반 (19파일, 2,055 대사)
- [x] PC_m2q41athfsto (36) → ATHFSTO
- [x] PC_m2q5a04frmer (211) → FRMER
- [x] PC_m2q5a04son (47) → Farmers_Son
- [x] PC_m2q5a04wife (46) → WIFE
- [x] PC_m2q5c02ptrol (38) → NPC_P_small
- [x] PC_m2q5c12gking (62) → GKING
- [x] PC_m2q5d15prsnr (53) → NPC_P_small
- [x] PC_m2q5e03nglat (60) → NGLAT
- [x] PC_m2q5f07crtkr (104) → CRTKR
- [x] PC_m2q5l01dydd (40) → NPC_D_small
- [x] PC_m2q5l01gam (67) → GAM
- [x] PC_m2q5l01grkan (48) → GRKAN
- [x] PC_m2q5l01mtmin (84) → MTMIN
- [x] PC_m2q5l01wtres (40) → NPC_W_small
- [x] PC_m2q5n17yunti (57) → YUNTI
- [x] PC_m2q5zshaldr (49) → ZSHALDR
- [x] PC_m2q6a02aarin (541) → AARIN ★대형
- [x] PC_m2q6a02abeth (403) → ABETH ★대형
- [x] PC_m2q6bdeath (69) → BDEATH

### OC-챕터3 (40파일, 3,378 대사)
- [x] PC_m3blackstore (32) → NPC_B_small
- [x] PC_m3deathcleric (77) → DEATHCLERIC
- [x] PC_m3q00sold (47) → SOLD
- [x] PC_m3q01a01aari (281) → AARI ★대형
- [x] PC_m3q01a01aver (46) → AVER
- [x] PC_m3q01a01haed (125) → HAED
- [x] PC_m3q01a01igla (73) → IGLA
- [x] PC_m3q01a01neur (111) → NEUR
- [x] PC_m3q01a01rolk (106) → ROLK
- [x] PC_m3q01a01yusa (101) → YUSA
- [x] PC_m3q01a01zed (62) → ZED
- [x] PC_m3q01a08crom (121) → CROM
- [x] PC_m3q01a09riba (107) → RIBA
- [x] PC_m3q01a10anda (75) → ANDA
- [x] PC_m3q01a11lill (185) → LILL
- [x] PC_m3q02a10bret (60) → BRET
- [x] PC_m3q02a10ecke (39) → NPC_E_small
- [x] PC_m3q02a10ecwi (44) → ECWI
- [x] PC_m3q02a11dama (173) → DAMA
- [x] PC_m3q02allsapp (132) → ALLSAPP
- [x] PC_m3q02g08loka (51) → NPC_L_small
- [x] PC_m3q02g17gols (84) → Slave_Worker
- [x] PC_m3q02g19gols (84) → Slave_Worker
- [x] PC_m3q02g21gols (84) → Slave_Worker
- [x] PC_m3q02golspirit (36) → NPC_G_small
- [x] PC_m3q03d08zoka (66) → ZOKA
- [x] PC_m3q04a02obul (35) → NPC_O_small
- [x] PC_m3q04a03uths (41) → NPC_U_small
- [x] PC_m3q04c03akul (72) → Akulatraxas
- [x] PC_m3q04f02gorg (79) → GORG
- [x] PC_m3q04g08woga (57) → WOGA
- [x] PC_m3q04h04drag (26) → NPC_D_small
- [x] PC_m3q04h07klau (138) → KLAU
- [x] PC_m3q3a01rang (92) → RANG
- [x] PC_m3q3a02vaath (37) → NPC_V_small
- [x] PC_m3q3b09nax (116) → NAX
- [x] PC_m3q3c03arwyl (68) → ARWYL
- [x] PC_m3q3c07hodd (66) → HODD
- [x] PC_m3q3c10sdrgn (81) → SDRGN
- [x] PC_m3q3d05balor (68) → BALOR

### OC-챕터4 (11파일, 1,078 대사)
- [x] PC_m4_finalhaedra (49) → FINALHAEDRA
- [x] PC_m4q01a04aari (175) → Aarin_Gend
- [x] PC_m4q01a04haed (114) → Haedraline
- [x] PC_m4q01a04nash (124) → Nasher_Alagondar
- [x] PC_m4q01a06luce (53) → Luce_1
- [x] PC_m4q01a07tran (105) → Trancar
- [x] PC_m4q01b11oldm (43) → Asgard
- [x] PC_m4q01b25arib (226) → ARIB ★대형
- [x] PC_m4q01c03arch (46) → ARCH
- [x] PC_m4q01d02pala (66) → PALA
- [x] PC_m4q01deathcleric (77) → DEATHCLERIC

### OC-동료 (7파일 + Henchman 6파일, 약 4,710 대사)
- [ ] PC_nw_hen_bod (779) → Henchman_BOD ★대형
- [ ] PC_nw_hen_dae (850) → Henchman_DAE ★대형
- [ ] PC_nw_hen_gal (875) → Henchman_GAL ★대형
- [ ] PC_nw_hen_gri (719) → Henchman_GRI ★대형
- [ ] PC_nw_hen_lin (928) → Henchman_LIN ★대형
- [ ] PC_nw_hen_sha (928) → Henchman_SHA ★대형
- [ ] PC_nw_g_animal (40) → Henchman_NW_G_ANIMAL

### OC-챕터2 러스칸 (29파일, 3,465 대사) ✅ 완료
- [x] PC_2q4a_aruph (101) → ARUPH
- [x] PC_2q4a_bridgegd (99) → BRIDGEGD
- [x] PC_2q4a_colmarr (76) → COLMARR
- [x] PC_2q4a_elynwyd (187) → ELYNWYD
- [x] PC_2q4a_galrone (130) → Galrone
- [x] PC_2q4a_jadale (165) → Lady_Jadale
- [x] PC_2q4a_londa (154) → LONDA
- [x] PC_2q4a_luskinfo_m (68) → LUSKINFO_M
- [x] PC_2q4a_luskintinfo (68) → LUSKINTINFO
- [x] PC_2q4a_luskmerch (54) → LUSKMERCH
- [x] PC_2q4a_waitress (41) → NPC_W_small
- [x] PC_2q4c_bela (136) → BELA
- [x] PC_2q4c_crtinlng (70) → CRTINLNG
- [x] PC_2q4c_erb (158) → ERB
- [x] PC_2q4c_oreth (153) → ORETH
- [x] PC_2q4c_rhaine (154) → Rhaine
- [x] PC_2q4c_yvette (129) → Yvette
- [x] PC_2q4d_evaine (79) → EVAINE
- [x] PC_2q4d_kurth (217) → High_Captain_Kurth ★대형
- [x] PC_2q4d_prisoner (81) → PRISONER_1
- [x] PC_2q4e_baram (215) → High_Captain_Baram ★대형
- [x] PC_2q4f_outcast (92) → Ghoul_Outcast
- [x] PC_2q6a_captain (78) → CAPTAIN
- [x] PC_2q6b_orcambass (117) → Gurak_Entrailspiller
- [x] PC_2q6b_yeanasha (120) → Yeanasha
- [x] PC_2q6c_nyphithys (179) → NYPHITHYS
- [x] PC_2q6c_rimardo (111) → RIMARDO
- [x] PC_2q6d_arklem (101) → ARKLEM
- [x] PC_2q6d_deltagar (132) → DELTAGAR

### XP2 본편 (94파일, 9,635 대사)
- [x] PC_pre_argali (102) → ARGALI
- [x] PC_pre_daelan (80) → DAELAN
- [x] PC_pre_deekin (82) → DEEKIN
- [x] PC_pre_durnan (257) → DURNAN ★대형
- [x] PC_pre_grayban (68) → GRAYBAN
- [x] PC_pre_linu (63) → LINU
- [x] PC_pre_parley (63) → PARLEY
- [x] PC_pre_sharwyn (64) → SHARWYN_1
- [x] PC_pre_tamsil (74) → TAMSIL
- [x] PC_pre_tanarell (58) → TANARELL
- [x] PC_pre_tomi (60) → TOMI
- [x] PC_q1_daschnaya (78) → DASCHNAYA_1
- [x] PC_q1_haniah (162) → HANIAH
- [x] PC_q1_katriana (177) → Katriana
- [x] PC_q1bguard (59) → Hilltop_Guard
- [x] PC_q1bnora (97) → Nora_Blake
- [x] PC_q1bszaren (142) → BSZAREN ← 1수정(말투)
- [x] PC_q1btorias (78) → BTORIAS ← 1수정(오타)
- [x] PC_q1dkobold (71) → DKOBOLD
- [x] PC_q1dlodar (93) → Lodar_the_Tavernmaster ← 1수정(조사)
- [x] PC_q1fblacksmith (184) → FBLACKSMITH
- [x] PC_q1ferran (129) → Ferran_Valiantheart
- [x] PC_q1footrumgut (90) → FOOTRUMGUT
- [x] PC_q1ggilford (59) → Gilford
- [x] PC_q1gpiper (112) → Piper
- [x] PC_q1herbalist (57) → HERBALIST
- [x] PC_q1hkobold (38) → NPC_H_small
- [x] PC_q1idaschnaya (56) → Daschnaya ← 1수정(이름)
- [x] PC_q1ifurten (57) → IFURTEN ← 1수정(말투)
- [x] PC_q1ikatriana (134) → IKATRIANA ← 1수정(오역)
- [x] PC_q1ruralnathan (91) → Nathan_Hurst
- [x] PC_q1ruralrebecca (92) → Becka_Hurst
- [x] PC_q1storeszaren (72) → Szaren
- [x] PC_q2_nilmaldor (114) → Spirit_of_Nilmaldor
- [x] PC_q2_urko (108) → Urko
- [x] PC_q2a_ali2 (176) → ALI2
- [x] PC_q2acavallas (67) → Cavallas
- [x] PC_q2adaelan (88) → ADAELAN
- [x] PC_q2agrayban (98) → AGRAYBAN
- [x] PC_q2agrovel (59) → AGROVEL
- [x] PC_q2alinu (98) → ALINU
- [x] PC_q2amadame (86) → AMADAME ← 1수정(맞춤법)
- [x] PC_q2anathyrra (110) → ANATHYRRA ← 4수정(맞춤법)
- [x] PC_q2aparley (63) → APARLEY
- [x] PC_q2asharwyn (94) → ASHARWYN
- [x] PC_q2asobrey (73) → ASOBREY ← 2수정(오타+서술체)
- [x] PC_q2atanarell (73) → ATANARELL
- [x] PC_q2atomi (97) → ATOMI
- [x] PC_q2aypguard (35) → NPC_A_small
- [x] PC_q2azesyyr (61) → AZESYYR
- [x] PC_q2b03ogrehighmag (71) → OGREHIGHMAG
- [x] PC_q2cberger (52) → CBERGER
- [x] PC_q2crakbrit (62) → CRAKBRIT ← 2수정(서술체+오타)
- [x] PC_q2crakshasa1 (102) → CRAKSHASA1 ← 1수정(띄어쓰기)
- [x] PC_q2d2slaver (58) → SLAVER
- [x] PC_q2d_halaster (45) → Halaster_Blackcloak ← 4수정(띄어쓰기)
- [x] PC_q2delderbrain (72) → DELDERBRAIN ← 4수정(말투통일)
- [x] PC_q2e_kelgaras (192) → KELGARAS
- [x] PC_q2evilnymph (95) → EVILNYMPH
- [x] PC_q3_blumberg (83) → BLUMBERG
- [x] PC_q3_gishnak (207) → GISHNAK ★대형 — NPC "즐나"→"즈나" 오타 수정
- [x] PC_q3_glendir (103) → GLENDIR
- [x] PC_q3_musharak (222) → MUSHARAK ★대형 — NPC 하오체 통일 3건 (해요체→하오체)
- [x] PC_q3_nafeeli (85) → Nafeeli
- [x] PC_q3b_sphinx (135) → SPHINX
- [x] PC_q3san_deva (99) → SAN_DEVA
- [x] PC_q3vil_leader (60) → LEADER
- [x] PC_q3vil_man_1 (61) → MAN_1
- [x] PC_q3vil_woman_1 (64) → WOMAN_1
- [x] PC_q4b_dahanna (90) → DAHANNA — NPC "상대" 중복 제거 1건
- [x] PC_q4c_aghaaz (118) → AGHAAZ — PC 띄어쓰기 1건, NPC 하오체 통일/띄어쓰기/용어통일 4건
- [x] PC_q4c_ferron (119) → FERRON — PC "창조주"→"제작자" 용어통일 3건
- [x] PC_q4c_ghost (70) → GHOST — NPC "영혼 보석"→"영혼석" 용어통일, "레버리지"→"패" 1건
- [x] PC_q5_arzig (178) → ARZIG
- [x] PC_q5_attiz (91) → ATTIZ
- [x] PC_q5_jnah (295) → JNAH ★대형
- [x] PC_q5_klumph (115) → KLUMPH
- [x] PC_q5_torias (78) → TORIAS_1
- [x] PC_q5_tymofarar (455) → TYMOFARAR ★최대 — PC "마법이 관심 가"→"마법에 관심 있어" 조사 수정 1건
- [x] PC_q5a_jasmeena (69) → Jasmeena — NPC "팔으니"→"파니" ㄹ탈락 수정 1건
- [x] PC_q5a_worguard (56) → WORGUARD
- [x] PC_q5b_garrick (142) → Garrick_Halassar
- [x] PC_q5b_priest (182) → Minister_of_Ao
- [x] PC_q5b_valana (64) → VALANA
- [x] PC_q6_deekin (299) → DEEKIN ★대형 ✓
- [x] PC_q6_greeters (56) → GREETERS — "사원"→"신전" 통일
- [x] PC_q6_guard (55) → GUARD_1 — "바래요"→"바라요"
- [x] PC_q6_medusa (83) → MEDUSA ✓
- [x] PC_q6_merchant (61) → MERCHANT ✓
- [x] PC_q6_priest (95) → PRIEST — "거울 파편"→"거울 조각", CSV따옴표 수정
- [x] PC_q6_queen (66) → Shaori — CSV따옴표 수정
- [x] PC_q6_the_fool (119) → THE_FOOL — "파편"→"조각","사원"→"신전","파에냐"→"파엔야"
- [x] PC_q7_cut_val0c (70) → CUT_VAL0C ✓
- [x] PC_q7dhermit (142) → DHERMIT ✓

### XP-동료 (17파일 + Henchman, 약 12,000 대사)
- [x] PC_xp1_drogan_conv (114) → DROGAN_CONV ✓
- [ ] PC_xp1_hen_dee (1330) → Henchman_DEE ★최대 [헨치맨 스킵]
- [ ] PC_xp1_hen_dor (697) → Henchman_DOR ★대형 [헨치맨 스킵]
- [ ] PC_xp1_hen_xan (802) → Henchman_XAN ★대형 [헨치맨 스킵]
- [x] PC_xp1_q1ayala (230) → AYALA ✓
- [x] PC_xp1_q1drogan (81) → DROGAN ✓
- [x] PC_xp1_q1xanos (33) → (없음) ✓
- [ ] PC_xp2_hen_dae (595) → Henchman_DAE ★대형 [헨치맨 스킵]
- [ ] PC_xp2_hen_dee (1655) → Henchman_DEE ★최대 [헨치맨 스킵]
- [ ] PC_xp2_hen_linu (368) → Henchman_LINU [헨치맨 스킵]
- [ ] PC_xp2_hen_nat (976) → Henchman_NAT ★대형 [헨치맨 스킵]
- [ ] PC_xp2_hen_shar (497) → Henchman_SHAR ★대형 [헨치맨 스킵]
- [ ] PC_xp2_hen_template (197) → Henchman_TEMPLATE [헨치맨 스킵]
- [ ] PC_xp2_hen_tomi (448) → Henchman_TOMI ★대형 [헨치맨 스킵]
- [ ] PC_xp2_hen_val (1047) → Henchman_VAL ★최대 [헨치맨 스킵]
- [x] PC_xp2_nathyrra (109) → NATHYRRA — 직역 어색 문장 수정 1건
- [x] PC_xp2_seer (245) → SEER ✓

### XP2-기타 (20파일, 4,591 대사)
- [ ] PC_h2_devil_gruul (157) → Gruul_the_Quarry_Boss
- [ ] PC_h2_devil_info (56) → DEVIL_INFO
- [ ] PC_h2_ghost_aribeth (986) → GHOST_ARIBETH ★최대
- [ ] PC_h2_ghost_generic (216) → GHOST_GENERIC
- [ ] PC_h2_ghost_info (92) → GHOST_INFO
- [ ] PC_h2_pilg_generic (59) → PILG_GENERIC
- [ ] PC_h2_pilg_info (224) → PILG_INFO
- [ ] PC_h2_pilg_sensei (618) → PILG_SENSEI ★대형
- [ ] PC_h3_sleepingman (612) → SLEEPINGMAN ★대형
- [ ] PC_h5_knower_places (61) → KNOWER_PLACES
- [ ] PC_h7_knower_names (251) → KNOWER_NAMES
- [ ] PC_h9_mephistophele (122) → MEPHISTOPHELE
- [ ] PC_hx_smith_conv (35) → NPC_S_small
- [ ] PC_x2_associate (432) → Henchman_X2_ASSOCIATE ★대형
- [ ] PC_x2_djinn (87) → Henchman_X2_DJINN
- [ ] PC_x2_gatekeeper (180) → Henchman_X2_GATEKEEPER
- [ ] PC_x2_guardian (154) → GUARDIAN
- [ ] PC_x2_iw_enserric (167) → Henchman_X2_IW_ENSERRIC
- [ ] PC_x2_iw_start (53) → IW_START
- [ ] PC_x2_p_portalston (29) → NPC_H_small

### 소규모(small) 파일 (15파일, 7,414 대사) ✅ 완료
- [x] PC_E_small (14) → NPC_E_small
- [x] PC_A_small (24) → NPC_A_small
- [x] PC_R_small (25) → NPC_R_small
- [x] PC_K_small (33) → NPC_K_small
- [x] PC_S_small (37) → NPC_S_small
- [x] PC_W_small (39) → William_Rey
- [x] PC_B_small (47) → NPC_B_small
- [x] PC_C_small (55) → NPC_C_small, NPC_R_small
- [x] PC_X_small (135) → NPC_H_small, VALEN
- [x] PC_N_small (157) → Barkeep, Barmaid 등
- [x] PC_P_small (201) → 다수 NPC 파일
- [x] PC_H_small (243) → 다수 NPC 파일
- [x] PC_OTHERS_small (262) → 다수 NPC 파일
- [x] PC_Q_small (2739) → 다수 NPC 파일 ★최대
- [x] PC_M_small (3403) → 다수 NPC 파일 ★최대

### 기타 (10파일, 896 대사)
- [ ] PC_ashtara (142) → Ashtara_Asabi_Merchant
- [ ] PC_bk_sim (40) → NPC_B_small
- [ ] PC_catapult (50) → NPC_C_small
- [ ] PC_dagget (84) → Dagget_Filth
- [ ] PC_friendly (89) → FRIENDLY
- [ ] PC_nwgencustomer (69) → NWGENCUSTOMER
- [ ] PC_riisi (204) → Riisi
- [ ] PC_serious (40) → NPC_S_small
- [ ] PC_stonebutler (68) → Stone_Butler
- [ ] PC_x0_skill_ctrap (110) → Henchman_X0_SKILL_CTRAP

## 진행 현황
- **소규모(small) 파일**: 15파일 7,414대사 ✅ 완료
- **OC-프롤로그/챕터1 (m0q01)**: 20파일 ✅ 완료
- **OC-챕터1 본편 (m1q1)**: 20파일 ✅ 완료
- **OC-챕터1 지구별 (m1q2~m1q5)**: 46파일 ✅ 완료
- **OC-챕터1 최종+기타 (m1q6)**: 11파일 ✅ 완료
- **OC-챕터2 (m2q)**: 98파일 ✅ 완료
- **OC-챕터2 러스칸 (2q4/2q6)**: 29파일 ✅ 완료
- **OC-챕터3 (m3q)**: 40파일 ✅ 완료
- **OC-챕터4 (m4q)**: 11파일 ✅ 완료
- **OC-동료 (Henchman)**: 스킵 (추후 진행)
- **XP2 본편**: 진행 중


## 우선순위 제안 (다음 단계)
1. 스토리 중요도 높은 파일 먼저 (Aribeth, Fenthick, Aarin, Nasher 등 주요 NPC)
2. ★대형/★최대 파일은 시간이 많이 걸리므로 분할 작업
3. 동료 파일은 양이 많지만 이전 세션에서 이미 일부 점검됨
