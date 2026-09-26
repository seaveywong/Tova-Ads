# -*- coding: utf-8 -*-
"""域名模糊搜索词库（2026-09-26：用户反馈选购域名不支持模糊搜索）。

用途：suggest 模糊模式做「包含匹配」——用户输入品牌词/片段（如 oak、marke），
从词库找出包含该片段的词（oakwood、market）× 后缀生成候选。
选词口径：常用英文 + 商业/科技语感 + 3-9 字母为主（域名友好）。
扩展：直接往 WORDS 里加词即可（小写、纯字母）。
"""
_WORDS_RAW = """
oak oakwood oakley oakland oakville oaktree oakwood oakforest
maple cedar birch willow aspen rowan hazel elm ash pine fir palm
rose lily iris daisy jasmine violet lotus tulip orchid heather fern moss ivy sage
mountain hill valley river lake ocean sea wave tide shore coast island bay cove
storm thunder cloud rain snow frost ice ember flame spark blaze torch flare
sun moon star dawn dusk twilight aurora comet nova nebula orbit lunar solar
sky cloud breeze gust zephyr wind gale storm calm serene tranquil
wolf fox eagle hawk raven crow owl deer stag bear lion tiger panda koala
whale dolphin shark ray fin shell coral reef krill seal otter
bee ant wasp moth cricket beetle spider web silk
swift falcon crane heron swan dove sparrow robin wren finch kestrel
gem jewel ruby opal pearl coral amber jade onyx quartz topaz
gold silver bronze copper iron steel titanium cobalt nickel zinc
crimson scarlet maroon indigo violet azure cobalt teal ivory ebony
peak summit crest ridge cliff canyon mesa plateau dune desert oasis
forest grove meadow field prairie tundra jungle woods thicket glade
trail path road journey quest voyage odyssey trek roam wander drift
arrow blade edge point tip spike lance dart bolt quiver shield armor
crown throne royal regal noble knight squire herald banner crest
forge smith craft build make shape mold cast carve hew polish
key lock gate portal door entry vault cache store keep hold
core heart soul mind brain nerve pulse beat rhythm tempo
spark flash glow shine gleam shimmer glimmer gloss luster
echo voice sound tone chord melody harmony rhythm tune song
pixel byte bit code script logic syntax kernel module plugin stack
cloud server host node mesh grid cluster lattice matrix array vector
quantum photon proton neutron atom ion plasma fusion fission
flux field force energy power charge current volt amp ohm watt
lens focus zoom iris scope prism mirror lens beam ray laser
vector vertex axis orbit spiral helix vortex swirl ripple
delta omega sigma lambda alpha gamma theta kappa psi phi chi rho tau
zen calm peace still quiet hush serene mellow gentle smooth
swift rapid quick flash brisk agile nimble deft keen sharp
bright vivid bold brave daring valiant gallant heroic epic saga
fable legend myth lore tale story chronicle annal archive
harbor haven refuge shelter nest den burrow roost perch
beacon lamp torch lumen candle lantern gleam glow
compass map chart atlas globe sphere world plane realm domain
cipher rune glyph sigil token emblem badge seal stamp mark
brand label stamp etch engrave imprint impress
venture quest venture leap bound jump spring vault hurdle
climb ascend rise soar glide sail drift float hover
anchor moor dock pier wharf quay marina harbor
harvest yield reap sow seed sprout bloom blossom flourish thrive
root stem branch leaf petal thorn bark trunk twig
grain wheat corn barley oat rice maize flax hemp
mill forge foundry kiln furnace oven hearth anvil
loom weave knit braid plait twist spin twine
vault arch dome tower spire pinnacle summit apex zenith
fable fox clever sly cunning witty wise sage guru mentor
atlas cosmos galaxy starlight starlit moonbeam moonlight sunbeam
tidal estuary lagoon marsh swamp bog fen mire
peak pike ridge arete col pass gap gorge ravine
north south east west nord sud orient polar boreal austral
urban city metro town borough quarter district zone sector
lane alley avenue boulevard street road way path track
plaza square market bazaar fair expo showcase gallery
bank trust union guild league alliance fellowship band crew team
pact bond tie link bridge span connect join merge blend fuse
pulse signal beacon relay router switch hub bridge gateway
canvas easel brush palette pigment mural fresco sketch draft
verse prose poem rhyme lyric ballad hymn anthem ode
stage drama scene act play script theater drama comedy
rhythm tempo beat groove vibe flow swing bounce
jazz blues soul funk rock metal punk disco techno house
violin piano drum flute harp lute lyre organ chime bell
festival gala feast banquet carnival parade fiesta
harvest autumn fall winter spring summer season epoch era age
pioneer settler voyager explorer scout pathfinder wayfinder
guard sentry watch ward keep vigil patrol scout
shield ward defend guard protect secure safe fortress citadel bastion
strategy tactic maneuver ploy gambit move play
chess checker dice card deal hand draw shuffle
gemstone crystal geode druzy prism facet karat
ivory ebony walnut mahogany teak bamboo rattan wicker
copper kettle pot pan jar jug vase urn crate
anchor keel hull mast sail rig deck bow stern
harbor lighthouse beacon pier jetty wharf
signal flare rocket probe drone rover satellite
nucleus core kernel seed germ embryo spawn hatch brood
flock herd swarm school pride pack troop colony hive
migrate wander nomad roamer drifter traveler tourist
haven oasis retreat lodge cabin cottage villa manor estate
orchard grove vineyard arboretum greenhouse conservatory
harvest granary silo barn coop stable pen kennel
forge workshop studio atelier lab institute academy
library archive museum gallery exhibit collection treasury
council senate assembly panel board committee jury
charter statute code law rule canon doctrine creed
crest coat shield heraldry lineage dynasty legacy heir
pivot hinge axis axle wheel gear cog cam lever
piston crank shaft turbine rotor propeller thruster jet
furnace boiler steam vapor mist fog haze smog
dew frost rime hail sleet flurry blizzard
puddle pond creek brook stream rivulet cascade waterfall
gorge abyss chasm pit hollow cavern grotto cave
summit plateau terrace ledge shelf sill sill
brisk crisp keen acute sharp subtle fine
grand noble lofty towering majestic sublime
simple plain modest humble basic plain
modern sleek crisp fresh novel new recent
classic vintage retro antique archaic old
future tomorrow destiny fate fortune chance luck
muse inspire spark ignite kindle stir arouse
dream vision fancy fantasy illusion mirage reverie
wish hope faith trust belief creed conviction
valor virtue honor merit grace charm appeal
truth verity fact real genuine authentic bona
bliss joy delight cheer glad merry jolly
zest gusto vigor vim pep drive push thrust
grit grits tenacity grit resolve will spine backbone
grace poise finesse flair panache style elan
chic classy swank posh smart dapper sharp
vogue trend fad craze mania boom surge
peak prime optimal best top apex max ultra
prime primo elite select choice premier first
tidy neat clean crisp clear pure
swift fleet racing speedy rapid express
steady stable firm solid robust sturdy
bright radiant beaming glowing shining dazzling
deep profound vast immense cosmic infinite
calm tranquil placid serene composed collected
bold daring audacious brave fearless intrepid
clever cunning crafty shrewd astute sharp
urban metro cosmopolitan global worldwide universal
local native home domestic inland
wild feral untamed rugged raw rough
tame gentle meek mild soft
swift nimbly agilely deftly skillfully
herald heralds forerunner vanguard avant precursor
alpha prime origin genesis dawn birth
apex acme peak summit crest zenith pinnacle
vertex apogee climax capstone crowning
nexus junction junction crossroad interchange hub
matrix lattice grid mesh weave web net
pulse cadence meter tempo pace rate speed
tempo rhythm swing groove flow cadence
harmony concord accord unity peace amity
discord strife clash feud rivalry contest
duel dual twin pair duo couple dyad
triad trio triple triplets three trey
quartet quad four
pentad penta five quint
sextet hex six
seven sept
octo eight
nova supernova stellar astral celestial
lunar solar helio sol
astro cosmic galactic universal
meteor asteroid comet halley
planet orbit revolve rotate spin turn
axis tilt wobble sway
gravity pull draw attract magnet
repel push thrust propel drive
force momentum inertia mass weight
velocity speed swift rapid
accelerate hasten hurry rush dash
brake halt stop pause rest
resume continue persist endure last
fade wane decline ebb dwindle shrink
grow wax swell expand bloom thrive
bloom blossom flower flourish thrive prosper
wither wilt fade decay decline
renew refresh revive restore regenerate
reform reshape remodel rebuild reconstruct
invent devise create originate conceive
design plan draft outline sketch
model pattern template prototype sample
test trial probe check verify
prove validate confirm certify endorse
seal sign stamp ratify enact
law legal lawful valid just fair
right duty role task job chore
work labor toil effort strive
play game sport match contest tourney
win lose draw tie victor champ
prize trophy medal ribbon laurel crown
reward award merit honor tribute
cheer applause acclaim praise laud extol
fan follower devotee loyal faithful
crowd throng mob mass swarm
rally gather assemble convene meet
feast dine sup eat taste savor
brew roast bake grill broil stew
brew ale lager stout porter cider
wine grape vine vintage barrel cask
toast cheer salute clink raise
mug cup glass stein chalice goblet
plate dish bowl platter tray
spoon fork knife ladle whisk
chef cook baker brewer vintner
kitchen pantry larder cellar attic
home house abode dwelling residence domicile
room chamber hall parlor study den
porch patio deck terrace veranda
garden yard lawn plot bed border
fence hedge wall gate stile
path walk promenade stroll ramble
sit stay rest relax unwind repose
sleep slumber doze nap snooze
wake rise awake rouse stir
morn morning daybreak sunrise day
noon midday afternoon eve evening
night midnight dusk gloaming dark
shade shadow umbra penumbra gloom
light bright clear fair sunny
dim faint pale wan dull
glow gleam glint glisten glitter sparkle
shine shimmer gloss sheen polish burnish
mirror reflect echo repeat copy
image picture photo graphic portrait scene
view vista panorama outlook prospect
scene setting stage backdrop milieu
color hue tint shade tone
paint dye stain pigment wash
draw sketch trace outline contour
shape form figure mold cast
line curve arc bow bend twist
angle slope slant tilt lean
square cube box block brick
circle round ring hoop loop
sphere ball globe orb pellet
cylinder tube pipe duct vent
pyramid cone spire pinnacle obelisk
column pillar post pole mast
beam girder joist rafter truss
frame chassis shell hull casing
roof ceiling canopy awning tarp
floor deck ground terra land
wall partition screen fence barrier
door gate entry portal threshold
window pane sash glass casement
lock latch bolt clasp hasp
hook nail screw bolt rivet
tool kit gear rig apparatus appliance
machine engine motor dynamo turbine
wire cable cord line strand
plug socket outlet jack port
switch lever knob button key
dial gauge meter scale index
clock watch timer hourglass
bell chime gong alarm signal
whistle horn siren hailer
flag banner pennant standard ensign
sign symbol mark token badge
label tag ticket stub pass
card note memo letter script
book tome volume folio manual
page leaf sheet slip scrap
ink pen quill nib stylus
paper parchment vellum papyrus
stamp seal wax imprint brand
envelope packet parcel bundle bale
box crate chest trunk case
basket hamper pail bucket tub
bag sack pouch wallet purse
pack bundle sheaf stack pile
shelf rack stand bracket ledge
drawer cabinet cupboard closet locker
chest trunk casket reliquary
vault safe strongbox coffer cache
treasure hoard stockpile reserve store
wealth riches fortune bounty plenty
gold gilt aureate golden gilded
silver argent silvery argent
money coin cash currency tender
price cost rate fee charge
value worth merit quality grade
deal trade bargain swap barter
buy purchase order acquire procure
sell vend market broker deal
shop store outlet bazaar mart
mall plaza arcade emporium
buyer seller trader merchant vendor
customer client patron guest visitor
host innkeeper landlord master owner
tenant lodger guest roomer boarder
invite greet welcome hail salute
meet gather convene assemble muster
talk speak converse chat discuss
say tell state express convey
hear listen heed attend hark
see look view watch observe
gaze glance peer stare glimpse
show display exhibit present reveal
hide conceal mask cloak shroud
find discover locate detect uncover
seek search quest probe explore
choose select pick elect prefer
decide judge determine settle resolve
plan intend aim propose scheme
start begin launch initiate open
end finish close conclude wrap
pause wait linger dwell abide
hasten hurry rush speed race
return revert recur repeat replay
send ship dispatch forward relay
receive accept take get obtain
give grant bestow confer donate
share divide split portion allot
keep retain hold reserve save
lose mislay drop forfeit squander
find regain recover retrieve reclaim
gain profit earn win garner
spend pay expend disburse outlay
save spare reserve store stock
invest stake venture risk wager
yield return profit dividend interest
loss deficit shortfall debt arrears
balance scale even level equal
surplus excess extra spare superfluity
short lack want need require
ample plenteous abundant lavish copious
sparse scant meager scanty lean
full filled laden packed brimming
empty void blank vacant hollow
hole gap void cavity hollow
fill plug stop stuff pack
pour spill drain empty dump
flow stream course current flux
flux reflux influx outflow stream
wave ripple surge swell billow
tide ebb flow current drift
pool pond lake mere tarn
brook creek rivulet stream runnel
river stream watercourse creek
delta estuary mouth inlet firth
shore coast strand beach sands
bank brink edge rim verge
brim lip mouth muzzle snout
edge border margin fringe skirt
line row rank file tier
row column file string series
series sequence chain string run
chain link yoke fetter leash
knot tie bend hitch loop
loop ring circle cycle orbit
cycle round turn phase stage
phase stage step degree gradation
step pace stride tread footstep
track trail path trace footprint
trace track vestige mark sign
mark sign token symbol emblem
clue hint cue lead signal
guide lead steer pilot direct
direct point aim level orient
aim target goal objective mark
goal end purpose aim intent
plan scheme design project blueprint
scheme plot design contrive devise
project undertaking venture enterprise venture
enterprise venture firm business company
company firm house concern outfit
group band team crew party squad
squad crew team troop band
gang clique circle set coterie
club society association league union
union league alliance pact compact
pact treaty accord compact deal
deal contract bargain accord pact
terms clause article provision stipulation
rule regulation statute law ordinance
law rule code canon precept
code cipher cryptogram key secret
secret hidden covert arcane privy
hidden unseen invisible veiled masked
reveal unveil disclose expose bare
show display exhibit bare expose
view vista scene sight prospect
sight vision eyesight glimpse glance
vision dream fantasy fancy ideal
ideal model paragon standard exemplar
standard norm benchmark measure gauge
measure gauge meter rule scale
scale ratio proportion balance weight
weight mass heft gravity force
force power might strength vigor
power energy force vigor vim
energy vigor vitality zip zest
zest gusto relish savor zest
savor relish taste flavor savor
flavor savor tang zest piquancy
spice herb seasoning relish zest
salt brine brack saline briny
sweet sugar honey saccharine sweet
sour tart acid acerb tart
bitter acrid harsh sharp bitter
sharp keen acute edged pointed
blunt dull obtuse rounded edgeless
smooth sleek polished slick glossy
rough coarse gritty raspy harsh
coarse crude rough unrefined rude
fine subtle delicate refined dainty
pure clean clear unsullied pristine
clear transparent lucid limpid crystalline
opaque dense solid murky cloudy
cloudy overcast hazy misty foggy
mist fog haze smog vapor
steam vapor fume mist dew
dew frost rime hoar glaze
ice glacier floe berg shelf
freeze chill frost cool numb
warm heat thaw melt warm
hot scorching burning fiery blazing
burn blaze flame flare kindle
kindle ignite light spark fire
fire flame blaze inferno pyre
ash cinder ember soot char
smoke fume vapor reek haze
spark flash flicker gleam glint
flash blink flare flicker pulse
glow ember shine beam radiate
beam ray shaft stream gleam
radiate shine glow blaze flare
shine gleam glitter sparkle dazzle
sparkle glister glitter scintillate
dark dim dusky gloomy murky
night nocturnal midnight starlit moonlit
day daily diurnal daylight daytime
sun solar sunny sunlight sunshine
moon lunar moonbeam moonlight crescent
star stellar starlight starry astral
planet planetary globe world earth
earth terra soil ground land
land terrain tract parcel plot
plot lot parcel tract acreage
field meadow pasture grassland lea
grass lawn turf sward verdure
green verdant lush leafy grassy
gold golden gilt aureate gilded
blue azure cerulean cobalt sapphire
red crimson scarlet ruby rosy
white ivory chalky snowy milky
black ebony jet sable pitch
gray slate ash grizzled hoar
brown umber tan brunette tawny
yellow golden amber lemon citron
orange tangerine citrus amber
purple violet amethyst plum mauve
pink rose blush coral salmon
swift fast rapid quick fleet
slow sluggish gradual leisurely slow
fast quick speedy rapid rapid
rapid swift fast quick fleet
quick prompt ready nimble agile
agile nimble deft handy adept
deft skillful adept expert practiced
expert adept skilled proficient veteran
master adept expert wizard guru
wizard mage sorcerer enchanter conjurer
sage seer oracle prophet diviner
seer visionary dreamer idealist utopian
hero champion paladin protector guardian
guard guardian warden keeper sentry
sentinel watchman lookout picket scout
scout spy recon explorer pathfinder
pathfinder wayfinder guide scout pilot
pilot captain skipper master helmsman
helmsman steersman pilot navigator skipper
navigator wayfarer traveler voyager explorer
voyager traveler pilgrim sojourner tourist
tourist traveler visitor guest stranger
stranger outsider newcomer foreigner alien
alien foreign exotic strange odd
odd strange peculiar queer quaint
quaint curious odd unusual bizarre
rare scarce uncommon unusual singular
common ordinary usual everyday commonplace
plain simple homely unadorned austere
fancy ornate elaborate decorated gilded
grand splendid magnificent imposing stately
stately majestic regal princely royal
royal regal kingly sovereign imperial
imperial regal royal majestic august
noble aristocratic patrician gentle highborn
knight cavalier paladin chevalier
squire esquire attendant retainer vassal
herald courier messenger herald forerunner
messenger courier bearer envoy emissary
envoy emissary delegate agent deputy
agent proxy deputy emissary rep
broker agent middleman factor dealer
dealer trader merchant trafficker vendor
vendor seller hawker peddler chapman
buyer purchaser client customer patron
patron sponsor backer supporter angel
backer sponsor underwriter guarantor angel
investor shareholder stakeholder financier capitalist
financier banker lender creditor investor
banker teller cashier lender loaner
audit account ledger journal register
record archive file dossier dossier
dossier file folder binder jacket
page leaf folio sheet quire
chapter section division part book
book volume tome library archive
library archive repository collection stacks
study research inquiry investigation probe
inquiry quest investigation inquest survey
survey review inspection scrutiny audit
test exam trial quiz check
trial test experiment assay try
experiment trial test empirical pilot
pilot trial beta prototype model
prototype sample mock demo pilot
demo sample specimen model pattern
pattern design motif theme style
style fashion mode manner way
manner mode fashion style tone
tone mood air flavor savor
mood temper humor frame vein
spirit soul essence core heart
heart core marrow essence pith
pith gist kernel substance core
substance matter material stuff body
matter material substance stuff fabric
fabric textile cloth weave tissue
texture grain weave fiber thread
thread strand filament fiber yarn
yarn thread strand string cord
cord rope cable line hawser
rope cable line strand hawser
knot loop bend hitch bight
weave braid plait twine interlace
braid plait weave twist twine
twist coil spiral wind twine
coil spiral helix whorl volute
spiral helix coil whorl scroll
scroll roll volume coil wreath
wreath garland crown coronal chaplet
coronet crown diadem tiara
tiara diadem coronet circlet
circlet ring band hoop halo
halo nimbus aureole corona glory
glory splendor luster brilliance radiance
brilliance luster sheen glow gleam
gleam glimmer spark flash flicker
flicker flutter waver flicker flare
waver sway swing oscillate vibrate
vibrate oscillate quiver tremble throb
throb pulse beat hammer pound
beat throb pulse tick palpitate
tick tock beat click clack
click tap knock rap pat
pat tap touch stroke caress
touch tap feel handle finger
feel sense perceive discern sense
sense feel discern perceive notice
notice note mark observe regard
observe watch view witness see
witness behold view observe survey
behold view notice sight discern
vision sight eye view gaze
gaze stare peer look behold
stare gaze peer gape gawk
glance peek glimpse flash dart
peek glance peep peer spy
peep glimpse glance peek peer
peer gaze look stare squint
squint peer peer squint squinny
look see view glance behold
view outlook vista scene prospect
scene tableau setting stage mise
stage scene act episode scene
act deed action exploit feat
feat exploit achievement accomplishment deed
achievement feat triumph victory win
triumph victory win conquest laurel
laurel honor glory renown fame
fame renown repute celebrity name
name title appellation designation label
title heading caption rubric headline
headline heading title banner lead
banner flag standard ensign pennant
pennant streamer banderole flag
flag colors banner standard jack
jack flag ensign pennant colors
colors palette hues tints shades
palette range scope array gamut
array range gamut spectrum scope
spectrum range span gamut scale
span stretch extent reach sweep
reach range scope sweep radius
radius range reach orbit compass
compass range reach ambit scope
ambit range extent reach orbit
extent range scope span reach
scope range reach horizon ken
horizon skyline vista prospect scope
skyline horizon contour profile outline
profile outline contour silhouette shape
silhouette outline profile shadow contour
contour outline profile line silhouette
outline sketch draft skeleton frame
skeleton frame framework chassis shell
framework structure skeleton frame scaffold
structure framework fabric frame frame
frame structure chassis shell body
body frame hull shell chassis
hull shell crust husk pod shell
shell husk pod hull crust
crust shell rind bark coat
rind peel skin husk shell
peel skin rind strip pare
skin peel hide pelt derma
hide pelt skin fell leather
leather hide skin fur pelt
fur pelt hide wool fleece
wool fleece fur hair fiber
hair lock strand tuft shock mane
mane hair crest plume pompom
plume feather quill feather crest
feather plume quill pin feather
quill pen feather plume nib
pen quill stylus nib scriber
scribe clerk writer scrivener notary
writer author scribe novelist penman
author writer composer creator originator
creator author maker inventor builder
maker builder creator mason wright
wright maker builder smith mason
smith forger smithy metalworker ironsmith
forge smithy foundry smelter furnace
foundry forge smelter kiln oven
kiln oven furnace hearth forge
hearth fireside stove furnace hearth
stove range furnace hearth cooker
oven stove kiln furnace rotisserie
cook chef baker roast broil
bake roast broil grill toast
grill broil barbecue roast sear
sear scorch char singe brand
brand mark trademark stamp emblem
trademark brand logo mark emblem
logo emblem insignia badge crest
insignia badge emblem crest arms
badge pin medal emblem chevron
medal decoration award ribbon star
ribbon band strip streamer braid
strip band stripe ribbon slash
stripe streak strip band bar
streak stripe strip band ribbon
band strip stripe ribbon belt
belt band girdle sash cincture
sash belt band girdle cordon
cordon cord line rope circle
cord string line twine strand
twine string cord strand rope
rope cord cable hawser line
hawser cable rope towline guys
towline hawser cable towrope rope
tow pull haul drag tug
pull tug haul drag draw
haul pull drag lug tote
drag pull haul trail trail
trail drag track path trace
path trail footpath way track
way path route road passage
route way road course itinerary
course route bearing heading tack
bearing heading azimuth course vector
vector bearing course azimuth heading
heading bearing course direction vector
direction bearing orientation heading azimuth
orientation direction aspect facing frontage
aspect facing orientation façade front
face front visage countenance mug
visage face countenance look mien
look aspect appearance seeming guise
appearance look aspect semblance surface
surface face outside exterior shell
exterior outside surface façade skin
outside exterior surface facing skin
inner interior inside inward inward
interior inside inner inward internal
internal inner interior domestic home
inside interior inner inward internal
core center heart middle nucleus
center core middle heart hub
middle center mid midst median
midst middle center thick heart
heart center core middle marrow
nucleus core center hub kernel
hub center nucleus focus node
focus center hub nucleus point
point tip apex peak vertex
tip point end extremity nib
end tip point terminus close
terminus end terminal final stop
terminal end terminus depot station
station depot terminal stop stand
stop station halt terminus stand
halt stop pause cease desist
pause halt stop rest break
rest pause repose break respite
repose rest relaxation ease leisure
ease comfort repose relaxation relief
comfort ease relief solace console
solace comfort console relief condole
relief ease comfort solace aid
aid help assist succor relief
help aid assist abet support
support aid help assist back
back support sponsor endorse uphold
endorse support back sanction approve
approve sanction endorse ratify okay
sanction approve endorse bless permit
permit allow let license sanction
allow permit let enable grant
grant allow permit confer bestow
deny refuse decline reject forbid
refuse deny decline reject repudiate
decline refuse reject demur decrease
reject refuse decline spurn rebuff
accept receive take approve admit
admit accept receive acknowledge concede
acknowledge admit own concede grant
own admit acknowledge concede confess
confess own admit acknowledge disclose
disclose reveal expose uncover divulge
reveal disclose unveil bare expose
expose disclose reveal uncover unmask
uncover expose reveal disclose unearth
unearth expose dig excavate discover
discover find uncover reveal detect
detect discover find sense descry
descry detect discern discover espy
discern perceive distinguish detect recognize
recognize discern identify know distinguish
identify recognize name determine pinpoint
determine decide resolve settle fix
decide determine resolve conclude choose
choose pick select elect prefer
prefer choose favor lean opt
opt choose elect pick prefer
elect choose select vote pick
select choose pick elect cull
cull pick select choose reject
sort sift cull winnow select
sift sort screen strain filter
filter sift strain screen purify
strain filter sift screen purify
screen filter sift sort vet
vet screen check examine inspect
examine inspect check view scrutinize
inspect examine check review audit
review inspect examine reconsider revise
revise review amend modify reform
amend revise reform correct emend
correct amend rectify reform fix
fix repair mend correct patch
repair fix mend restore rehabilitate
mend repair patch fix darn
patch mend repair piece fix
restore repair renovate renew refresh
renovate restore refurbish revamp renew
refresh renew revive restore rejuvenate
revive refresh resurrect restore rekindle
renew refresh revive regenerate restore
regenerate renew revive restore regrow
create originate invent produce generate
produce create make manufacture generate
generate produce create engender beget
make build construct produce fabricate
build make construct erect assemble
construct build erect fabricate assemble
erect build construct raise upraise
raise erect lift elevate hoist
lift raise elevate hoist heave
elevate raise lift uplift exalt
exalt elevate extol glorify laud
extol exalt praise laud magnify
praise extol laud commend applaud
applaud praise clap acclaim salute
acclaim applaud hail cheer praise
cheer applaud acclaim root encourage
encourage cheer hearten inspire embolden
inspire encourage hearten spur animate
animate inspire enliven vitalize quicken
enliven animate cheer brighten liven
quicken animate accelerate hasten speed
accelerate quicken hasten hurry expedite
expedite hasten accelerate dispatch rush
rush hurry hasten speed dash
dash rush dart sprint race
sprint dash race run scamper
run race sprint dash jog
jog trot run canter lope
trot canter jog gallop jog
gallop canter sprint race bolt
bolt dash dart race scurry
scurry scamper scuttle hurry dart
scamper scurry skip hop frisk
skip hop caper gambol leap
leap jump spring vault bound
jump leap spring vault hop
spring leap jump vault bounce
vault leap jump spring hurdle
hurdle leap vault jump obstacle
obstacle hurdle barrier block impediment
barrier obstacle block wall dam
block barrier obstacle stop clog
clog block obstruct choke jam
obstruct block bar impede hinder
impede hinder obstruct hamper retard
hinder impede obstruct retard thwart
thwart foil baffle frustrate thwart
foil thwart baffle defeat frustrate
defeat foil beat overcome conquer
overcome conquer defeat beat surmount
surmount overcome conquer surpass exceed
surpass exceed outdo outstrip eclipse
exceed surpass outdo transcend top
outdo surpass exceed beat excel
excel surpass outshine outdo surpass
outshine eclipse surpass excel overshine
eclipse overshadow outshine excel obscure
overshadow eclipse cloud dim overcast
cloud overshadow dim becloud obscure
dim obscure darken cloud overshadow
obscure dim darken cloud befog
darken dim obscure cloud blacken
lighten brighten illumine kindle light
brighten lighten illumine shine lighten
illumine enlighten light bright irradiate
enlighten illumine edify instruct teach
teach instruct educate train school
instruct teach direct educate coach
educate teach instruct school train
train educate school discipline drill
drill train exercise practice discipline
practice drill rehearse exercise train
rehearse practice drill prepare prep
prepare ready equip fit outfit
equip outfit furnish arm rig
furnish equip supply provide outfit
supply furnish provide stock provision
provide supply furnish yield afford
afford provide supply yield give
yield provide supply bear produce
bear produce yield bring forth
bring fetch carry convey transport
carry bear convey transport lug
convey carry transport transmit fetch
transport carry convey ship transmit
transmit convey send signal broadcast
broadcast transmit beam air relay
beam broadcast transmit shine radiate
signal transmit beckon flag wave
wave signal beckon gesture salute
gesture signal wave motion gesticulate
motion gesture move sign wave
move motion stir budge shift
shift move transfer relocate budge
transfer shift move convey reassign
relocate transfer move resettle migrate
migrate relocate move travel shift
travel journey tour voyage roam
journey travel trek trip passage
trip journey excursion outing jaunt
excursion trip outing expedition jaunt
outing excursion trip expedition picnic
expedition excursion voyage expedition safari
safari expedition hunt quest chase
hunt quest pursue chase stalk
pursue chase follow trail quest
follow pursue trail chase succeed
trail follow track pursue chase
track trail follow trace pursue
trace track follow trail pursue
seek search quest pursue chase
search seek comb scour ransack
comb search scour rake sweep
scour search scrub polish rake
scrub scour polish clean wash
wash rinse launder bathe scrub
rinse wash flush cleanse dip
clean wash cleanse purify tidy
purify clean refine filter distill
refine purify polish perfect distill
polish burnish shine smooth gloss
perfect refine complete finish polish
complete finish perfect fulfill consummate
finish complete end close polish
fulfill complete satisfy realize effect
satisfy fulfill content gratify please
please gratify delight gladden satisfy
delight please charm gladden enchant
charm delight captivate enchant bewitch
captivate charm enchant fascinate allure
fascinate captivate charm engross absorb
absorb engross soak steep imbibe
soak steep drench saturate souse
steep soak saturate macerate infuse
infuse instill imbue inject steep
instill infuse implant inculcate imbue
imbue infuse instill saturate permeate
permeate pervade saturate imbue interpenetrate
pervade permeate suffuse diffuse overspread
suffuse pervade infuse overspread tint
diffuse spread scatter disperse disseminate
spread diffuse scatter disperse strew
scatter spread strew disperse sow
disperse scatter dissipate dispel scatter
dissipate disperse scatter squander fritter
dispel dissipate scatter banish expel
banish expel exile eject evict
expel banish eject oust evict
eject expel oust oust emit
oust eject expel displace remove
remove take off detach withdraw extract
detach remove disconnect separate unfasten
separate detach divide part split
divide separate split portion share
split divide cleave rive fissure
cleave split sever rive rift
sever cut cleave sunder amputate
cut sever shear clip trim
shear cut clip fleece poll
clip cut trim snip crop
trim clip prune sheer cut
prune trim lop top clip
lop prune cut fell sever
fell cut hew chop down
hew chop cut hack hew
chop cut hack hew mince
hack chop cut hew gash
gash slash cut incision slit
slash gash cut incise gash
incise carve cut engrave score
carve incise engrave sculpt chisel
engrave incise etch carve grave
etch engrave corrode bite incise
sculpt carve model mold fashion
mold sculpt shape model form
shape form mold fashion model
form shape mold fashion figure
figure form shape shape pattern
pattern model form shape design
design plan devise contrive draft
devise design invent conceive plan
invent devise originate create contrive
conceive invent devise imagine design
imagine conceive envision fancy invent
envision imagine visualize conceive foresee
visualize envision imagine picture see
picture visualize imagine image depict
depict picture portray represent limn
portray depict represent picture delineate
represent portray depict stand figure
symbolize represent signify stand betoken
signify mean denote imply symbolize
denote signify mean import indicate
imply signify suggest hint connote
suggest imply hint propose insinuate
hint suggest intimate imply allude
allude refer hint mention touch
mention refer cite name allude
refer mention cite allude apply
cite quote refer adduce mention
quote cite recite repeat adduce
recite repeat rehearse narrate quote
narrate recite tell relate recount
tell narrate recount relate recite
recount narrate relate tell detail
relate narrate tell recount describe
describe relate depict portray characterize
characterize describe depict portray distinguish
portray depict describe characterize paint
paint depict portray color render
render depict translate interpret paint
interpret render construe explain translate
explain interpret expound clarify elucidate
clarify explain elucidate enlighten explicate
elucidate clarify explain illuminate expound
illuminate light brighten illumine irradiate
irradiate illuminate light brighten emblaze
glorify exalt extol laud magnify
magnify amplify enlarge augment amplify
amplify magnify augment strengthen swell
enlarge magnify augment amplify dilate
augment enlarge amplify increase magnify
increase augment enlarge multiply amplify
multiply increase reproduce propagate breed
propagate multiply breed spread disseminate
breed propagate multiply engender spawn
spawn breed generate produce hatch
hatch spawn brood incubate breed
incubate hatch brood brew foster
foster nurture cultivate nurse incubate
nurture foster nourish nurse cherish
nourish nurture feed sustain aliment
feed nourish sustain fodder forage
sustain nourish support maintain uphold
maintain sustain support keep preserve
preserve maintain conserve keep protect
conserve preserve save husband economize
save preserve rescue redeem salvage
rescue save salvage deliver ransom
deliver rescue save free liberate
liberate free release emancipate deliver
release liberate free loose unloose
free liberate release loose emancipate
loose release loosen free slack
loosen loose slack release relax
slack loosen relax slacken loosen
relax loosen slack ease unwind
unwind relax decompress rest loosen
"""
# 去重排序 + 只留 3-12 位纯 ASCII 字母词（isalpha 对中文也 True——须 isascii 双守卫）
WORDS = sorted({w for w in _WORDS_RAW.split() if w.isascii() and w.isalpha() and 3 <= len(w) <= 12})
