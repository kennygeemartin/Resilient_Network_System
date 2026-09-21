import java.io.*;
import java.nio.file.*;
import java.util.*;
import org.cloudbus.cloudsim.*;
import org.cloudbus.cloudsim.core.*;
import org.cloudbus.cloudsim.power.PowerHost;
import org.cloudbus.cloudsim.provisioners.RamProvisionerSimple;
import org.cloudbus.cloudsim.sdn.overbooking.*;
import org.fog.application.*;
import org.fog.application.selectivity.SelectivityModel;
import org.fog.entities.*;
import org.fog.placement.*;
import org.fog.policy.AppModuleAllocationPolicy;
import org.fog.scheduler.StreamOperatorScheduler;
import org.fog.utils.*;
import org.fog.utils.distribution.Distribution;

/** SI seconds, MI, MIPS, bytes, W and J. No measured network metrics are exported. */
public class ManufacturingExperiment {
    static Properties cfg = new Properties();
    static List<FogDevice> devices = new ArrayList<>();
    static List<Sensor> sensors = new ArrayList<>();
    static List<Actuator> actuators = new ArrayList<>();
    static PrintWriter tuples, energy, placement, sensorLog;
    static Path output;
    static String architecture;
    static long seed;
    static double number(String key) { return Double.parseDouble(cfg.getProperty(key)); }
    static int integer(String key) { return (int)number(key); }

    static class ObservedBroker extends FogBroker {
        ObservedBroker() throws Exception { super("broker"); }
        @Override public void processEvent(SimEvent ev) {
            if (ev.getTag() == CloudSimTags.CLOUDLET_RETURN) {
                Tuple t = (Tuple)ev.getData();
                tuples.printf(Locale.ROOT,"%d,%s,%s,%s,%.9f,%.9f,%.9f%n",t.getCloudletId(),
                    t.getAppId(),t.getDestModuleName(),CloudSim.getEntityName(ev.getSource()),
                    t.getExecStartTime(),t.getFinishTime(),t.getActualCPUTime());
            }
        }
    }
    static class ReplayDistribution extends Distribution {
        final double[] offsets;
        int index=0;
        double previous=0;
        ReplayDistribution(String text) {
            offsets=Arrays.stream(text.split(",")).mapToDouble(Double::parseDouble).toArray();
        }
        public double getNextValue() {
            if(index>=offsets.length) return number("duration_s")*2;
            double next=offsets[index++]; double delta=next-previous; previous=next;
            return Math.max(delta,number("min_event_s"));
        }
        public int getDistributionType() { return Distribution.DETERMINISTIC; }
        public double getMeanInterTransmitTime() { return number("period_s"); }
    }
    static class ObservedSensor extends Sensor {
        ObservedSensor(String name,String type,int user,String app,Distribution dist) {
            super(name,type,user,app,dist);
        }
        @Override public void transmit() {
            sensorLog.printf(Locale.ROOT,"%s,%s,%.9f%n",getName(),getTupleType(),CloudSim.clock());
            super.transmit();
        }
    }
    static class SeededSelectivity implements SelectivityModel {
        final double rate;
        final Random rng;
        SeededSelectivity(double rate,long seed) {this.rate=rate;this.rng=new Random(seed);}
        public boolean canSelect() { return rng.nextDouble()<rate; }
        public double getMeanRate() { return rate; }
        public double getMaxRate() { return rate; }
    }
    static class ObservedController extends Controller {
        static final int SAMPLE=900001,EXPORT=900002;
        ObservedController() {super("placement-controller",devices,sensors,actuators);}
        @Override public void startEntity() {
            super.startEntity();
            send(getId(),number("resource_interval_s"),SAMPLE);
        }
        @Override public void processEvent(SimEvent ev) {
            if(ev.getTag()==SAMPLE || ev.getTag()==FogEvents.STOP_SIMULATION) {
                for(FogDevice d:devices) sendNow(d.getId(),FogEvents.RESOURCE_MGMT);
                send(getId(),number("min_event_s"),EXPORT,ev.getTag()==FogEvents.STOP_SIMULATION);
                if(ev.getTag()==SAMPLE && CloudSim.clock()+number("resource_interval_s")<number("duration_s"))
                    send(getId(),number("resource_interval_s"),SAMPLE);
            } else if(ev.getTag()==EXPORT) {
                for(FogDevice d:devices)
                    energy.printf(Locale.ROOT,"%s,%.9f,%.9f,%.9f%n",d.getName(),CloudSim.clock(),
                        d.getEnergyConsumption(),d.getHost().getUtilizationOfCpu());
                if(Boolean.TRUE.equals(ev.getData())) {
                    tuples.flush();energy.flush();sensorLog.flush();placement.flush();
                    CloudSim.terminateSimulation();
                }
            } else super.processEvent(ev);
        }
    }
    static FogDevice device(String name,String profile,int level,double up,double down,double delay) throws Exception {
        List<Pe> pes=new ArrayList<>();
        for(int i=0;i<integer(profile+".pes");i++)
            pes.add(new Pe(i,new PeProvisionerOverbooking(number(profile+".mips_per_pe"))));
        PowerHost host=new PowerHost(FogUtils.generateEntityId(),new RamProvisionerSimple(integer(profile+".ram_mb")),
            new BwProvisionerOverbooking((long)number("host_bw")),(long)number("host_storage"),pes,
            new StreamOperatorScheduler(pes),new FogLinearPowerModel(number(profile+".busy_w"),number(profile+".idle_w")));
        List<Host> hosts=new ArrayList<>();hosts.add(host);
        FogDeviceCharacteristics characteristics=new FogDeviceCharacteristics("x86","Linux","Xen",host,0,0,0,0,0);
        FogDevice d=new FogDevice(name,characteristics,new AppModuleAllocationPolicy(hosts),new LinkedList<Storage>(),
            number("resource_interval_s"),up,down,delay,0);
        d.setLevel(level);devices.add(d);return d;
    }
    static Application application(int cell,int user) {
        String id="cell"+cell;
        Application a=Application.createApplication(id,user);
        for(String m:new String[]{"Ingest","Filter","Control","Analytics","Storage"})
            a.addAppModule(m+cell,integer("module_ram_mb"),integer("module_mips"),integer("module_size"));
        for(String type:new String[]{"C0","C1","C2"}) {
            a.addAppEdge(type+cell,"Ingest"+cell,number("cpu.Ingest"),number("tuple_bytes"),type+cell,Tuple.UP,AppEdge.SENSOR);
            a.addTupleMapping("Ingest"+cell,type+cell,"FILTER"+cell,new SeededSelectivity(1,seed+cell));
        }
        a.addAppEdge("Ingest"+cell,"Filter"+cell,number("cpu.Filter"),number("tuple_bytes"),"FILTER"+cell,Tuple.UP,AppEdge.MODULE);
        a.addAppEdge("Filter"+cell,"Control"+cell,number("cpu.Control"),number("tuple_bytes"),"CONTROL"+cell,Tuple.UP,AppEdge.MODULE);
        a.addAppEdge("Filter"+cell,"Analytics"+cell,number("cpu.Analytics"),number("tuple_bytes"),"ANALYTICS"+cell,Tuple.UP,AppEdge.MODULE);
        a.addAppEdge("Analytics"+cell,"Storage"+cell,number("cpu.Storage"),number("tuple_bytes"),"STORAGE"+cell,Tuple.UP,AppEdge.MODULE);
        a.addAppEdge("Control"+cell,"ACTUATOR"+cell,0,number("tuple_bytes"),"ACTUATE"+cell,Tuple.DOWN,AppEdge.ACTUATOR);
        a.addTupleMapping("Filter"+cell,"FILTER"+cell,"CONTROL"+cell,new SeededSelectivity(1,seed+cell));
        a.addTupleMapping("Filter"+cell,"FILTER"+cell,"ANALYTICS"+cell,new SeededSelectivity(number("analytics_fraction"),seed+100+cell));
        a.addTupleMapping("Analytics"+cell,"ANALYTICS"+cell,"STORAGE"+cell,new SeededSelectivity(1,seed+cell));
        a.addTupleMapping("Control"+cell,"CONTROL"+cell,"ACTUATE"+cell,new SeededSelectivity(1,seed+cell));
        a.setLoops(new ArrayList<AppLoop>());
        return a;
    }
    public static void main(String[] args) throws Exception {
        try(InputStream in=Files.newInputStream(Paths.get(args[0]))) {cfg.load(in);}
        output=Paths.get(args[1]);architecture=cfg.getProperty("architecture");seed=Long.parseLong(cfg.getProperty("seed"));
        tuples=new PrintWriter(Files.newBufferedWriter(output.resolve("tuples.csv"),StandardOpenOption.CREATE_NEW));
        energy=new PrintWriter(Files.newBufferedWriter(output.resolve("device_resources.csv"),StandardOpenOption.CREATE_NEW));
        placement=new PrintWriter(Files.newBufferedWriter(output.resolve("placement.csv"),StandardOpenOption.CREATE_NEW));
        sensorLog=new PrintWriter(Files.newBufferedWriter(output.resolve("sensor_emissions.csv"),StandardOpenOption.CREATE_NEW));
        tuples.println("tuple_id,app,module,device,start_s,finish_s,cpu_s");
        energy.println("device,simulation_s,energy_j,cpu_utilization");
        placement.println("module,device");sensorLog.println("sensor,traffic_class,simulation_s");
        Log.disable();CloudSim.init(1,Calendar.getInstance(),false,number("min_event_s"));
        Config.MAX_SIMULATION_TIME=integer("duration_s");
        Config.ENABLE_DYNAMIC_CLUSTERING=false;Config.ENABLE_STATIC_CLUSTERING=false;
        ObservedBroker broker=new ObservedBroker();
        FogDevice cloud=device("cloud","cloud",0,number("cloud_bw"),number("cloud_bw"),0);cloud.setParentId(-1);
        for(int cell=1;cell<=4;cell++) {
            FogDevice fog=device("fog"+cell,"fog",1,number("fog_bw"),number("fog_bw"),number("fog_cloud_delay_s"));
            fog.setParentId(cloud.getId());
            FogDevice act=device("act"+cell,"edge",2,number("edge_bw"),number("edge_bw"),number("edge_fog_delay_s"));act.setParentId(fog.getId());
            Actuator actuator=new Actuator("actuator"+cell,broker.getId(),"cell"+cell,"ACTUATOR"+cell);
            actuator.setGatewayDeviceId(act.getId());actuator.setLatency(number("min_event_s"));actuators.add(actuator);
            for(int sensor=1;sensor<=2;sensor++) {
                FogDevice edge=device("edge"+cell+"s"+sensor,"edge",2,number("edge_bw"),number("edge_bw"),number("edge_fog_delay_s"));edge.setParentId(fog.getId());
                for(String type:new String[]{"C0","C1","C2"}) {
                    String key="schedule."+cell+"."+sensor+"."+type;
                    if(cfg.getProperty(key,"").isEmpty()) continue;
                    Sensor s=new ObservedSensor(key,type+cell,broker.getId(),"cell"+cell,new ReplayDistribution(cfg.getProperty(key)));
                    s.setTransmissionStartDelay(0);s.setGatewayDeviceId(edge.getId());s.setLatency(number("min_event_s"));sensors.add(s);
                }
            }
        }
        ObservedController controller=new ObservedController();
        for(int cell=1;cell<=4;cell++) {
            Application a=application(cell,broker.getId());
            ModuleMapping mapping=ModuleMapping.createModuleMapping();
            for(String m:new String[]{"Ingest","Filter","Control","Analytics","Storage"}) {
                String destination=architecture.equals("A0") || m.equals("Analytics") || m.equals("Storage") ? "cloud" : "fog"+cell;
                mapping.addModuleToDevice(m+cell,destination);placement.println(m+cell+","+destination);
            }
            controller.submitApplication(a,new ModulePlacementMapping(devices,a,mapping));
        }
        CloudSim.startSimulation();CloudSim.stopSimulation();
        tuples.close();energy.close();placement.close();sensorLog.close();
    }
}
