# The filters added to this controller will be run for all controllers in the application.
# Likewise will all the methods added be available for all controllers.
class ApplicationController < ActionController::Base
  
  require 'xmlrpc/client'
  
  private
  def authorize
    unless session[:user_id]
      flash[:notice] = "Please log in"
      session[:jumpto] = request.parameters
      redirect_to :controller => "login", :action => "login"
    end
  end
  
  def defaults
    @username = 'joe'
    @password = 'honker'
    @hnzb_server = '192.168.2.2'
    @hnzb_password = 'changeme'
    @hnzb_port = 8760
  end

  def load_queue
    get_status_queue
    @queue = session[:cache][:queuelist]
  end
  
  def load_status
    get_status_queue
    @status = session[:cache][:status]
  end
  
  def get_status_queue
    session[:cache] ||= {:time => Time.now}
    if Time.now > session[:cache][:time]
      session[:cache].merge!({:status => server.call("status"),
                              :queuelist => server.call('list'),
                              :time => Time.at(Time.now+4)})
    end
  end
  
  def server()
    @server ||= XMLRPC::Client.new(@hnzb_server, "/", @hnzb_port, nil, nil, "hellanzb", @hnzb_password)
  end
end